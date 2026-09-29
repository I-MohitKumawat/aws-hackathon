import json
import re
import time
import uuid
from unittest.mock import patch
from datetime import datetime, timezone
import pytest

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from backend.app.agent import OllamaClient
from backend.app.models import Incident, Evidence

def test_w3c_trace_context_propagation():
    """
    Verifies W3C Trace Context propagation across service boundaries:
    1. Upstream service creates an active span and injects context into HTTP headers.
    2. Downstream service extracts context and starts a child span.
    3. Confirms identical trace_id and correct parent_span_id.
    """
    provider = TracerProvider()
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer("test.tracer")
    propagator = TraceContextTextMapPropagator()

    # Upstream: Checkout Service creates root span
    with tracer.start_as_current_span("POST /checkout") as root_span:
        root_trace_id = trace.format_trace_id(root_span.get_span_context().trace_id)
        root_span_id = trace.format_span_id(root_span.get_span_context().span_id)

        # Inject into outgoing HTTP headers
        carrier = {}
        propagator.inject(carrier)

        assert "traceparent" in carrier
        assert root_trace_id in carrier["traceparent"]

        # Downstream: Inventory Service receives headers and starts span
        extracted_ctx = propagator.extract(carrier)
        with tracer.start_as_current_span("inventory.reserve", context=extracted_ctx) as inv_span:
            inv_trace_id = trace.format_trace_id(inv_span.get_span_context().trace_id)
            inv_parent_id = trace.format_span_id(inv_span.parent.span_id)

            assert inv_trace_id == root_trace_id, "Downstream span must inherit exact trace ID"
            assert inv_parent_id == root_span_id, "Downstream span parent must match upstream span ID"

def test_multi_service_trace_correlation(client):
    """
    Ingests spans from three distinct microservices (Checkout, Inventory, Payment)
    sharing a single trace ID, and verifies cross-service trace correlation.
    """
    trace_id = f"ms_{uuid.uuid4().hex[:30]}"
    s_checkout_server = f"span_{uuid.uuid4().hex[:12]}"
    s_checkout_inv_client = f"span_{uuid.uuid4().hex[:12]}"
    s_inv_server = f"span_{uuid.uuid4().hex[:12]}"
    s_checkout_pay_client = f"span_{uuid.uuid4().hex[:12]}"
    s_pay_server = f"span_{uuid.uuid4().hex[:12]}"

    payload = {
        "resourceSpans": [
            # 1. Checkout Service Spans
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "checkout"}}]},
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": s_checkout_server,
                                "parentSpanId": None,
                                "name": "POST /checkout",
                                "startTimeUnixNano": "1727602330000000000",
                                "status": {"code": 1},
                            },
                            {
                                "traceId": trace_id,
                                "spanId": s_checkout_inv_client,
                                "parentSpanId": s_checkout_server,
                                "name": "call_inventory_service",
                                "startTimeUnixNano": "1727602331000000000",
                                "status": {"code": 1},
                            },
                            {
                                "traceId": trace_id,
                                "spanId": s_checkout_pay_client,
                                "parentSpanId": s_checkout_server,
                                "name": "call_payment_service",
                                "startTimeUnixNano": "1727602333000000000",
                                "status": {"code": 1},
                            },
                        ]
                    }
                ],
            },
            # 2. Inventory Service Span
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "inventory"}}]},
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": s_inv_server,
                                "parentSpanId": s_checkout_inv_client,
                                "name": "POST /inventory/reserve",
                                "startTimeUnixNano": "1727602331500000000",
                                "status": {"code": 1},
                            }
                        ]
                    }
                ],
            },
            # 3. Payment Service Span
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "payment"}}]},
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": s_pay_server,
                                "parentSpanId": s_checkout_pay_client,
                                "name": "POST /payment/process",
                                "startTimeUnixNano": "1727602333500000000",
                                "status": {"code": 1},
                            }
                        ]
                    }
                ],
            },
        ]
    }

    # Ingest batch
    resp = client.post("/api/v1/otlp/v1/traces", json=payload)
    assert resp.status_code == 202
    assert resp.json()["accepted_spans"] == 5

    # Query correlated trace via dedicated Trace API
    trace_resp = client.get(f"/api/v1/traces/{trace_id}")
    assert trace_resp.status_code == 200
    trace_data = trace_resp.json()

    assert trace_data["trace_id"] == trace_id
    assert trace_data["spans_count"] == 5
    assert set(trace_data["services"]) == {"checkout", "inventory", "payment"}
    assert trace_data["has_errors"] is False

    # Verify parent-child linkages across services
    spans_by_id = {s["span_id"]: s for s in trace_data["spans"]}
    assert spans_by_id[s_checkout_server]["parent_span_id"] is None
    assert spans_by_id[s_checkout_inv_client]["parent_span_id"] == s_checkout_server
    assert spans_by_id[s_inv_server]["parent_span_id"] == s_checkout_inv_client
    assert spans_by_id[s_inv_server]["service"] == "inventory"
    assert spans_by_id[s_pay_server]["parent_span_id"] == s_checkout_pay_client
    assert spans_by_id[s_pay_server]["service"] == "payment"

def test_downstream_inventory_failure_localization(client):
    """
    Simulates a transaction failing in the downstream Inventory service (out-of-stock).
    Confirms that the error span accurately identifies 'inventory' as the failing service
    and records the InventoryOutOfStockError exception.
    """
    trace_id = f"fail_inv_{uuid.uuid4().hex[:26]}"
    s_checkout = f"span_{uuid.uuid4().hex[:12]}"
    s_inv_error = f"span_{uuid.uuid4().hex[:12]}"

    payload = {
        "resourceSpans": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "checkout"}}]},
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": s_checkout,
                                "name": "POST /checkout",
                                "startTimeUnixNano": "1727602330000000000",
                                "status": {"code": 2, "message": "Downstream service 'inventory' failed"},
                            }
                        ]
                    }
                ],
            },
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "inventory"}}]},
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": s_inv_error,
                                "parentSpanId": s_checkout,
                                "name": "inventory.check_stock",
                                "startTimeUnixNano": "1727602330500000000",
                                "attributes": [
                                    {"key": "error.type", "value": {"stringValue": "OUT_OF_STOCK"}},
                                    {"key": "inventory.stock_level", "value": {"intValue": 0}},
                                ],
                                "events": [
                                    {
                                        "name": "exception",
                                        "timeUnixNano": "1727602330600000000",
                                        "attributes": [
                                            {"key": "exception.type", "value": {"stringValue": "InventoryOutOfStockError"}},
                                            {"key": "exception.message", "value": {"stringValue": "Item 'item_beta' is out of stock in warehouse-east"}},
                                        ],
                                    }
                                ],
                                "status": {"code": 2, "message": "Item out of stock"},
                            }
                        ]
                    }
                ],
            },
        ]
    }

    resp = client.post("/api/v1/otlp/v1/traces", json=payload)
    assert resp.status_code == 202

    trace_resp = client.get(f"/api/v1/traces/{trace_id}")
    assert trace_resp.status_code == 200
    trace_data = trace_resp.json()

    assert trace_data["has_errors"] is True
    error_spans = [s for s in trace_data["spans"] if s["severity"] == "error"]
    assert len(error_spans) >= 1

    # Pinpoint root cause to inventory service
    inv_err = next(s for s in error_spans if s["service"] == "inventory")
    assert inv_err["span_name"] == "inventory.check_stock"
    assert "InventoryOutOfStockError" in inv_err["message"]
    assert inv_err["attributes"]["error.type"] == "OUT_OF_STOCK"

def test_downstream_payment_failure_localization(client):
    """
    Simulates a transaction failing in the downstream Payment service (gateway decline).
    Confirms that the error span accurately identifies 'payment' as the failing service.
    """
    trace_id = f"fail_pay_{uuid.uuid4().hex[:26]}"
    s_checkout = f"span_{uuid.uuid4().hex[:12]}"
    s_pay_error = f"span_{uuid.uuid4().hex[:12]}"

    payload = {
        "resourceSpans": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "checkout"}}]},
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": s_checkout,
                                "name": "POST /checkout",
                                "startTimeUnixNano": "1727602340000000000",
                                "status": {"code": 2, "message": "Downstream payment failed"},
                            }
                        ]
                    }
                ],
            },
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "payment"}}]},
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": s_pay_error,
                                "parentSpanId": s_checkout,
                                "name": "payment.authorize",
                                "startTimeUnixNano": "1727602340800000000",
                                "attributes": [
                                    {"key": "error.type", "value": {"stringValue": "GATEWAY_DECLINED"}},
                                    {"key": "payment.gateway.status_code", "value": {"intValue": 402}},
                                ],
                                "events": [
                                    {
                                        "name": "exception",
                                        "timeUnixNano": "1727602340900000000",
                                        "attributes": [
                                            {"key": "exception.type", "value": {"stringValue": "PaymentGatewayError"}},
                                            {"key": "exception.message", "value": {"stringValue": "Payment gateway rejected transaction: card_issuer_declined"}},
                                        ],
                                    }
                                ],
                                "status": {"code": 2, "message": "Transaction declined by card issuer"},
                            }
                        ]
                    }
                ],
            },
        ]
    }

    resp = client.post("/api/v1/otlp/v1/traces", json=payload)
    assert resp.status_code == 202

    trace_resp = client.get(f"/api/v1/traces/{trace_id}")
    assert trace_resp.status_code == 200
    trace_data = trace_resp.json()

    assert trace_data["has_errors"] is True
    pay_err = next(s for s in trace_data["spans"] if s["service"] == "payment")
    assert pay_err["span_name"] == "payment.authorize"
    assert "PaymentGatewayError" in pay_err["message"]
    assert pay_err["attributes"]["error.type"] == "GATEWAY_DECLINED"

def test_multi_service_incident_association_and_deduplication(client):
    """
    Verifies that multi-service spans carrying 'incident.id' in attributes are
    automatically linked, can be queried by trace_id filter, and deduplicated on retry.
    """
    # 1. Create Incident
    inc_res = client.post("/api/v1/incidents", json={
        "title": "Payment Gateway Outage Incident",
        "service": "checkout",
        "severity": "critical",
        "started_at": "2026-09-29T10:00:00Z",
        "description": "Cross-service checkout failures due to payment gateway errors."
    })
    assert inc_res.status_code == 201
    incident_id = inc_res.json()["id"]

    trace_id = f"ms_inc_{uuid.uuid4().hex[:26]}"
    s1 = f"span_{uuid.uuid4().hex[:12]}"
    s2 = f"span_{uuid.uuid4().hex[:12]}"

    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "checkout"}},
                        {"key": "incident.id", "value": {"stringValue": incident_id}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": s1,
                                "name": "POST /checkout",
                                "startTimeUnixNano": "1727602350000000000",
                                "status": {"code": 1},
                            }
                        ]
                    }
                ],
            },
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "payment"}},
                        {"key": "incident.id", "value": {"stringValue": incident_id}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": s2,
                                "name": "payment.process",
                                "startTimeUnixNano": "1727602351000000000",
                                "status": {"code": 1},
                            }
                        ]
                    }
                ],
            },
        ]
    }

    # Ingest
    res1 = client.post("/api/v1/otlp/v1/traces", json=payload)
    assert res1.status_code == 202
    assert res1.json()["associated_spans"] == 2

    # Query evidence filtered by trace_id
    ev_res = client.get(f"/api/v1/incidents/{incident_id}/evidence?trace_id={trace_id}")
    assert ev_res.status_code == 200
    ev_data = ev_res.json()
    assert ev_data["total"] == 2
    assert {item["service"] for item in ev_data["items"]} == {"checkout", "payment"}

    # Retry exact same payload (deduplication check)
    res2 = client.post("/api/v1/otlp/v1/traces", json=payload)
    assert res2.status_code == 202
    assert res2.json()["accepted_spans"] == 2

    # Total evidence count must remain exactly 2
    ev_res2 = client.get(f"/api/v1/incidents/{incident_id}/evidence?trace_id={trace_id}")
    assert ev_res2.json()["total"] == 2

async def mock_multi_service_investigation(self, prompt, system=None, options=None, **kwargs):
    match = re.search(r"VALID EVIDENCE IDs:\s*(\[[^\]]+\])", prompt)
    ev_ids = json.loads(match.group(1)) if match else []
    return json.dumps({
        "summary": "Distributed transaction failed in downstream inventory service due to stock exhaustion.",
        "hypotheses": [
            {
                "id": "hyp_downstream_01",
                "description": "Downstream inventory service rejected reservation because item_beta is out of stock.",
                "status": "supported",
                "supporting_evidence": ev_ids,
                "contradicting_evidence": [],
                "missing_evidence": [],
                "next_step": "Check inventory warehouse-east stock reconciliation logs.",
            }
        ]
    })

def test_full_investigation_lifecycle_with_multi_service_trace(client):
    """
    Verifies that the AI investigation engine grounds its root-cause report
    in the multi-service trace evidence, citing the downstream failing span.
    """
    with patch.object(OllamaClient, "generate", new=mock_multi_service_investigation):
        # 1. Create Incident
        inc_res = client.post("/api/v1/incidents", json={
            "title": "Checkout Out-Of-Stock Cascading Failure",
            "service": "checkout",
            "severity": "high",
            "started_at": "2026-09-29T10:15:00Z",
            "description": "Checkout transactions failing during inventory reservation."
        })
        assert inc_res.status_code == 201
        incident_id = inc_res.json()["id"]

        # 2. Ingest multi-service failure trace
        trace_id = f"ms_life_{uuid.uuid4().hex[:26]}"
        span_inv_fail = f"span_{uuid.uuid4().hex[:12]}"
        nanos_2026 = str(int(datetime.fromisoformat("2026-09-29T10:16:00+00:00").timestamp() * 1e9))

        payload = {
            "resourceSpans": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "inventory"}},
                            {"key": "incident.id", "value": {"stringValue": incident_id}},
                        ]
                    },
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": trace_id,
                                    "spanId": span_inv_fail,
                                    "name": "inventory.check_stock",
                                    "startTimeUnixNano": nanos_2026,
                                    "attributes": [
                                        {"key": "error.type", "value": {"stringValue": "OUT_OF_STOCK"}},
                                    ],
                                    "events": [
                                        {
                                            "name": "exception",
                                            "timeUnixNano": nanos_2026,
                                            "attributes": [
                                                {"key": "exception.type", "value": {"stringValue": "InventoryOutOfStockError"}},
                                                {"key": "exception.message", "value": {"stringValue": "Item out of stock"}},
                                            ],
                                        }
                                    ],
                                    "status": {"code": 2, "message": "Out of stock"},
                                }
                            ]
                        }
                    ],
                }
            ]
        }
        ingest_res = client.post("/api/v1/otlp/v1/traces", json=payload)
        assert ingest_res.status_code == 202

        # 3. Start Investigation
        start_res = client.post(f"/api/v1/incidents/{incident_id}/investigations", json={
            "time_window": {
                "start": "2026-09-29T10:00:00Z",
                "end": "2026-09-29T10:30:00Z",
            }
        })
        assert start_res.status_code == 202
        job_id = start_res.json()["job_id"]

        # 4. Wait for completion
        for _ in range(30):
            job_res = client.get(f"/api/v1/investigations/{job_id}")
            if job_res.json()["status"] in ("completed", "failed"):
                break
            time.sleep(0.1)

        assert job_res.json()["status"] == "completed"

        # 5. Verify Report cites the downstream failing span
        report_res = client.get(f"/api/v1/investigations/{job_id}/report")
        assert report_res.status_code == 200
        report = report_res.json()
        assert len(report["hypotheses"]) > 0
        cited = report["hypotheses"][0]["supporting_evidence"]
        assert f"ev_span_{span_inv_fail}" in cited

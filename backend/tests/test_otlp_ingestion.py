import time
import json
import re
import uuid
from unittest.mock import patch
from datetime import datetime, timezone
import pytest
from backend.app.agent import OllamaClient
from backend.app.models import Incident, Evidence

SAMPLE_OTLP_TRACES = {
    "resourceSpans": [
        {
            "resource": {
                "attributes": [
                    {"key": "service.name", "value": {"stringValue": "checkout"}},
                    {"key": "service.version", "value": {"stringValue": "2.1.0"}},
                    {"key": "deployment.environment", "value": {"stringValue": "production"}},
                ]
            },
            "scopeSpans": [
                {
                    "scope": {
                        "name": "checkout.tracer",
                        "version": "1.0.0"
                    },
                    "spans": [
                        {
                            "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
                            "spanId": "00f067aa0ba902b7",
                            "parentSpanId": None,
                            "name": "POST /checkout",
                            "kind": 1,
                            "startTimeUnixNano": "1727602330000000000",
                            "endTimeUnixNano": "1727602331000000000",
                            "attributes": [
                                {"key": "http.method", "value": {"stringValue": "POST"}},
                                {"key": "http.status_code", "value": {"intValue": 200}},
                                {"key": "cart.items_count", "value": {"intValue": 3}},
                            ],
                            "events": [],
                            "status": {"code": 1, "message": "OK"}
                        },
                        {
                            "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
                            "spanId": "5fb397be34d23b0f",
                            "parentSpanId": "00f067aa0ba902b7",
                            "name": "db.acquire_connection",
                            "kind": 3,
                            "startTimeUnixNano": "1727602332000000000",
                            "endTimeUnixNano": "1727602337000000000",
                            "attributes": [
                                {"key": "db.system", "value": {"stringValue": "postgresql"}},
                                {"key": "error.type", "value": {"stringValue": "POOL_TIMEOUT"}},
                                {"key": "db.pool.max", "value": {"intValue": 20}},
                            ],
                            "events": [
                                {
                                    "timeUnixNano": "1727602337000000000",
                                    "name": "exception",
                                    "attributes": [
                                        {"key": "exception.type", "value": {"stringValue": "ConnectionPoolTimeoutError"}},
                                        {"key": "exception.message", "value": {"stringValue": "unable to obtain connection within 5000ms"}},
                                    ]
                                }
                            ],
                            "status": {"code": 2, "message": "Connection pool timeout"}
                        }
                    ]
                }
            ]
        }
    ]
}

def test_otlp_trace_ingestion_normalization(client):
    s1 = f"norm1_{uuid.uuid4().hex[:10]}"
    s2 = f"norm2_{uuid.uuid4().hex[:10]}"
    batch = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "checkout"}},
                        {"key": "service.version", "value": {"stringValue": "2.1.0"}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
                                "spanId": s1,
                                "name": "POST /checkout",
                                "startTimeUnixNano": "1790674330000000000",
                                "status": {"code": 1, "message": "OK"}
                            },
                            {
                                "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
                                "spanId": s2,
                                "name": "db.acquire_connection",
                                "startTimeUnixNano": "1790674332000000000",
                                "events": [
                                    {
                                        "name": "exception",
                                        "timeUnixNano": "1790674337000000000",
                                        "attributes": [
                                            {"key": "exception.type", "value": {"stringValue": "ConnectionPoolTimeoutError"}},
                                            {"key": "exception.message", "value": {"stringValue": "unable to obtain connection within 5000ms"}},
                                        ]
                                    }
                                ],
                                "status": {"code": 2, "message": "Connection pool timeout"}
                            }
                        ]
                    }
                ]
            }
        ]
    }
    res = client.post("/api/v1/otlp/v1/traces", json=batch)
    assert res.status_code == 202
    data = res.json()
    assert data["accepted_spans"] == 2
    assert data["rejected_spans"] == 0
    assert data["unassociated_spans"] == 2

def test_otlp_deduplication(client):
    s1 = f"dedup_{uuid.uuid4().hex[:10]}"
    batch = {
        "resourceSpans": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "checkout"}}]},
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
                                "spanId": s1,
                                "name": "POST /checkout",
                                "startTimeUnixNano": "1790674330000000000",
                                "status": {"code": 1, "message": "OK"}
                            }
                        ]
                    }
                ]
            }
        ]
    }
    # Ingest once
    res1 = client.post("/api/v1/otlp/v1/traces", json=batch)
    assert res1.status_code == 202
    assert res1.json()["accepted_spans"] == 1

    # Ingest same batch again (simulating Collector retry)
    res2 = client.post("/api/v1/otlp/v1/traces", json=batch)
    assert res2.status_code == 202
    assert res2.json()["accepted_spans"] == 1

def test_otlp_sensitive_data_redaction(client):
    s_auth = f"sec_{uuid.uuid4().hex[:10]}"
    payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "checkout"}},
                        {"key": "db.password", "value": {"stringValue": "super-secret-pass"}},
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "11112222333344445555666677778888",
                                "spanId": s_auth,
                                "name": "auth_call",
                                "startTimeUnixNano": "1790674330000000000",
                                "attributes": [
                                    {"key": "api_key", "value": {"stringValue": "sk-123456789"}},
                                    {"key": "http.request.header.authorization", "value": {"stringValue": "Bearer eyJhbGciOiJIUzI1NiJ9"}},
                                    {"key": "user.token", "value": {"stringValue": "secret-token-xyz"}},
                                    {"key": "normal.field", "value": {"stringValue": "harmless_value"}},
                                ],
                            }
                        ]
                    }
                ]
            }
        ]
    }
    res = client.post("/api/v1/otlp/v1/traces", json=payload)
    assert res.status_code == 202

def test_otlp_direct_incident_association(client):
    # Create incident first
    inc_res = client.post("/api/v1/incidents", json={
        "title": "Direct Tagged Incident",
        "service": "checkout",
        "severity": "high",
        "started_at": "2026-09-29T09:30:00Z",
        "description": "Testing direct tagging via span attribute"
    })
    assert inc_res.status_code == 201
    incident_id = inc_res.json()["id"]

    # Send span tagged with incident.id
    target_span_id = f"dir_{uuid.uuid4().hex[:10]}"
    payload = {
        "resourceSpans": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "checkout"}}]},
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "aaaa1111bbbb2222cccc3333dddd4444",
                                "spanId": target_span_id,
                                "name": "direct_tagged_span",
                                "startTimeUnixNano": "1790674330000000000",
                                "attributes": [
                                    {"key": "incident.id", "value": {"stringValue": incident_id}}
                                ],
                            }
                        ]
                    }
                ]
            }
        ]
    }
    res = client.post("/api/v1/otlp/v1/traces", json=payload)
    assert res.status_code == 202
    assert res.json()["associated_spans"] == 1

    # Verify evidence is immediately listed for this incident
    ev_res = client.get(f"/api/v1/incidents/{incident_id}/evidence")
    assert ev_res.status_code == 200
    items = ev_res.json()["items"]
    assert any(i["id"] == f"ev_span_{target_span_id}" for i in items)

def test_otlp_unlinked_then_explicit_associate(client):
    span_id = f"span_{int(time.time()*1000)}"[:16]
    # Send unlinked span
    payload = {
        "resourceSpans": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "checkout"}}]},
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": "bbbb2222cccc3333dddd4444eeee5555",
                                "spanId": span_id,
                                "name": "unlinked_checkout_span",
                                "startTimeUnixNano": "1727602330000000000",
                                "attributes": [
                                    {"key": "test.marker", "value": {"stringValue": "explicit_association"}}
                                ],
                            }
                        ]
                    }
                ]
            }
        ]
    }
    res = client.post("/api/v1/otlp/v1/traces", json=payload)
    assert res.status_code == 202
    assert res.json()["unassociated_spans"] == 1

    # Create incident
    inc_res = client.post("/api/v1/incidents", json={
        "title": "Post-Association Incident",
        "service": "checkout",
        "severity": "critical",
        "started_at": "2026-09-29T09:00:00Z",
        "description": "Correlating telemetry post-ingestion"
    })
    assert inc_res.status_code == 201
    incident_id = inc_res.json()["id"]

    # Explicitly associate telemetry
    assoc_res = client.post(f"/api/v1/incidents/{incident_id}/associate-telemetry", json={
        "service": "checkout"
    })
    assert assoc_res.status_code == 200
    assoc_data = assoc_res.json()
    assert assoc_data["associated_count"] >= 1
    assert assoc_data["incident_id"] == incident_id

    # Verify that the span is now returned under incident evidence
    ev_res = client.get(f"/api/v1/incidents/{incident_id}/evidence")
    assert ev_res.status_code == 200
    items = ev_res.json()["items"]
    assert any(i["id"] == f"ev_span_{span_id}" for i in items)

async def mock_ollama_investigation_generate(self, prompt, system=None, options=None, **kwargs):
    match = re.search(r"VALID EVIDENCE IDs:\s*(\[[^\]]+\])", prompt)
    ev_ids = json.loads(match.group(1)) if match else []
    return json.dumps({
        "summary": "Connection pool timeout observed in checkout service trace spans.",
        "hypotheses": [
            {
                "id": "hyp_01",
                "description": "Database connection acquisition exceeded maximum timeout under load.",
                "status": "supported",
                "supporting_evidence": ev_ids,
                "contradicting_evidence": [],
                "missing_evidence": [],
                "next_step": "Increase connection pool size or tune connection idle timeouts.",
            }
        ]
    })

def test_full_investigation_lifecycle_with_otlp_spans(client):
    with patch.object(OllamaClient, "generate", new=mock_ollama_investigation_generate):
        # 1. Create Incident
        inc_res = client.post("/api/v1/incidents", json={
            "title": "Checkout DB Connection Failure",
            "service": "checkout",
            "severity": "high",
            "started_at": "2026-09-29T09:20:00Z",
            "description": "Checkout transactions are failing with database timeout errors."
        })
        assert inc_res.status_code == 201
        incident_id = inc_res.json()["id"]

        # 2. Ingest OTLP Error Trace Span
        span_id = f"fail_{int(time.time()*1000)}"[:16]
        nanos_2026 = str(int(datetime.fromisoformat("2026-09-29T09:32:15+00:00").timestamp() * 1e9))
        payload = {
            "resourceSpans": [
                {
                    "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "checkout"}}]},
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": "cccc3333dddd4444eeee5555ffff6666",
                                    "spanId": span_id,
                                    "name": "db.query",
                                    "startTimeUnixNano": nanos_2026,
                                    "attributes": [
                                        {"key": "incident.id", "value": {"stringValue": incident_id}},
                                        {"key": "db.statement", "value": {"stringValue": "SELECT 1"}},
                                        {"key": "error.type", "value": {"stringValue": "POOL_TIMEOUT"}}
                                    ],
                                    "events": [
                                        {
                                            "name": "exception",
                                            "timeUnixNano": nanos_2026,
                                            "attributes": [
                                                {"key": "exception.type", "value": {"stringValue": "ConnectionPoolTimeoutError"}},
                                                {"key": "exception.message", "value": {"stringValue": "unable to obtain connection within 5000ms"}}
                                            ]
                                        }
                                    ],
                                    "status": {"code": 2, "message": "Connection pool timeout"}
                                }
                            ]
                        }
                    ]
                }
            ]
        }
        res = client.post("/api/v1/otlp/v1/traces", json=payload)
        assert res.status_code == 202

        # 3. Start Investigation
        start_res = client.post(f"/api/v1/incidents/{incident_id}/investigations", json={
            "time_window": {
                "start": "2026-09-29T09:00:00Z",
                "end": "2026-09-29T10:00:00Z",
            }
        })
        assert start_res.status_code == 202
        job_id = start_res.json()["job_id"]

        # 4. Wait for job completion
        for _ in range(30):
            job_res = client.get(f"/api/v1/investigations/{job_id}")
            assert job_res.status_code == 200
            status_val = job_res.json()["status"]
            if status_val in ("completed", "failed"):
                break
            time.sleep(0.1)

        assert status_val == "completed"

        # 5. Fetch and verify report cites the OTLP trace evidence ID
        report_res = client.get(f"/api/v1/investigations/{job_id}/report")
        assert report_res.status_code == 200
        report = report_res.json()
        assert report["incident_id"] == incident_id
        assert len(report["hypotheses"]) > 0
        cited_evidence = report["hypotheses"][0]["supporting_evidence"]
        expected_ev_id = f"ev_span_{span_id}"
        assert expected_ev_id in cited_evidence

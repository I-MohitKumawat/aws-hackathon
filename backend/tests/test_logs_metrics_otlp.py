import time
import json
import re
import uuid
from unittest.mock import patch, AsyncMock
from datetime import datetime, timezone
import pytest
from backend.app.agent import OllamaClient, EmbeddingClient
from backend.app.models import Incident, Evidence


def test_otlp_logs_ingestion_normalization(client):
    """Verify OTLP log records are normalized into Evidence records with correct fields."""
    inc_resp = client.post(
        "/api/v1/incidents",
        json={
            "title": "Log normalization test incident",
            "service": "checkout",
            "severity": "medium",
            "started_at": "2026-09-29T10:00:00Z",
        },
    )
    assert inc_resp.status_code == 201
    inc_id = inc_resp.json()["id"]

    uid = uuid.uuid4().hex[:8]
    t1 = str(int(time.time() * 1e9))
    t2 = str(int((time.time() + 1) * 1e9))
    span_id = f"span_{uid}"[:16]

    payload = {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "checkout"}},
                        {"key": "service.version", "value": {"stringValue": "2.1.0"}},
                    ]
                },
                "scopeLogs": [
                    {
                        "scope": {"name": "checkout.logger", "version": "1.0.0"},
                        "logRecords": [
                            {
                                "timeUnixNano": t1,
                                "severityNumber": 9,
                                "severityText": "INFO",
                                "body": {"stringValue": f"Processing order ord_{uid} for customer usr_99"},
                                "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
                                "spanId": span_id,
                                "attributes": [
                                    {"key": "incident.id", "value": {"stringValue": inc_id}},
                                    {"key": "order.id", "value": {"stringValue": f"ord_{uid}"}},
                                ],
                            },
                            {
                                "timeUnixNano": t2,
                                "severityNumber": 17,
                                "severityText": "ERROR",
                                "body": {"stringValue": "Connection pool timeout: unable to obtain connection within 5000ms. Authorization: Bearer topsecrettoken123"},
                                "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
                                "spanId": span_id,
                                "attributes": [
                                    {"key": "incident.id", "value": {"stringValue": inc_id}},
                                    {"key": "db.pool.active", "value": {"intValue": 20}},
                                    {"key": "db.pool.max", "value": {"intValue": 20}},
                                ],
                            },
                        ],
                    }
                ],
            }
        ]
    }

    with patch.object(EmbeddingClient, "generate_embeddings_batch", new_callable=AsyncMock, side_effect=lambda texts: [[0.1] * 384 for _ in texts]):
        resp = client.post("/api/v1/otlp/v1/logs", json=payload)
        assert resp.status_code == 202, resp.text
        data = resp.json()
        assert data["accepted_logs"] == 2
        assert data["associated_logs"] == 2

    # Query incident evidence
    ev_resp = client.get(f"/api/v1/incidents/{inc_id}/evidence")
    assert ev_resp.status_code == 200
    items = ev_resp.json()["items"]
    assert len(items) == 2

    error_log = next(i for i in items if i["severity"] == "error")
    assert error_log["type"] == "log"
    assert error_log["service"] == "checkout"
    assert "Connection pool timeout" in error_log["message"]
    # Sensitive bearer token should be redacted
    assert "topsecrettoken123" not in error_log["message"]
    assert "[REDACTED]" in error_log["message"]
    assert error_log["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert error_log["source"] in ("otel", "otlp")
    assert error_log["metadata"]["span_id"] == span_id


def test_otlp_metrics_ingestion_normalization(client):
    """Verify OTLP metric data points are normalized into Evidence records."""
    inc_resp = client.post(
        "/api/v1/incidents",
        json={
            "title": "Metric normalization test incident",
            "service": "checkout",
            "severity": "medium",
            "started_at": "2026-09-29T10:00:00Z",
        },
    )
    assert inc_resp.status_code == 201
    inc_id = inc_resp.json()["id"]

    uid = uuid.uuid4().hex[:8]
    t1 = str(int(time.time() * 1e9))
    t2 = str(int((time.time() + 1) * 1e9))

    payload = {
        "resourceMetrics": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "checkout"}},
                    ]
                },
                "scopeMetrics": [
                    {
                        "scope": {"name": "checkout.meter", "version": "1.0.0"},
                        "metrics": [
                            {
                                "name": "checkout.orders.total",
                                "description": "Total checkout orders handled",
                                "unit": "1",
                                "sum": {
                                    "dataPoints": [
                                        {
                                            "timeUnixNano": t1,
                                            "asInt": 15,
                                            "attributes": [
                                                {"key": "incident.id", "value": {"stringValue": inc_id}},
                                                {"key": "status", "value": {"stringValue": "success"}},
                                            ],
                                        }
                                    ]
                                },
                            },
                            {
                                "name": "checkout.db.pool.exhausted",
                                "description": "Whether checkout DB connection pool is exhausted",
                                "unit": "1",
                                "gauge": {
                                    "dataPoints": [
                                        {
                                            "timeUnixNano": t2,
                                            "asDouble": 1.0,
                                            "attributes": [
                                                {"key": "incident.id", "value": {"stringValue": inc_id}},
                                                {"key": "pool.name", "value": {"stringValue": f"pool_{uid}"}},
                                            ],
                                        }
                                    ]
                                },
                            },
                        ],
                    }
                ],
            }
        ]
    }

    with patch.object(EmbeddingClient, "generate_embeddings_batch", new_callable=AsyncMock, side_effect=lambda texts: [[0.1] * 384 for _ in texts]):
        resp = client.post("/api/v1/otlp/v1/metrics", json=payload)
        assert resp.status_code == 202, resp.text
        data = resp.json()
        assert data["accepted_metrics"] == 2
        assert data["associated_metrics"] == 2

    # Verify evidence records under incident
    ev_resp = client.get(f"/api/v1/incidents/{inc_id}/evidence")
    assert ev_resp.status_code == 200
    items = ev_resp.json()["items"]
    assert len(items) == 2

    pool_metric = next(i for i in items if "pool.exhausted" in i["message"])
    assert pool_metric["type"] == "metric"
    assert pool_metric["service"] == "checkout"
    assert pool_metric["severity"] == "error"  # pool.exhausted classified as error
    assert pool_metric["metadata"]["metric_name"] == "checkout.db.pool.exhausted"
    assert pool_metric["metadata"]["value"] == 1.0
    assert pool_metric["metadata"]["metric_type"] == "gauge"


def test_otlp_logs_and_metrics_deduplication(client):
    """Verify replayed logs and metrics with identical attributes are deduplicated."""
    unique_ts = str(int(time.time() * 1e9))
    uid = uuid.uuid4().hex[:8]
    payload_log = {
        "resourceLogs": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "inventory"}}]},
                "scopeLogs": [
                    {
                        "logRecords": [
                            {
                                "timeUnixNano": unique_ts,
                                "severityText": "WARN",
                                "body": {"stringValue": f"Inventory low for SKU-{uid}"},
                            }
                        ]
                    }
                ],
            }
        ]
    }

    with patch.object(EmbeddingClient, "generate_embeddings_batch", new_callable=AsyncMock, side_effect=lambda texts: [[0.05] * 384 for _ in texts]):
        # First ingest
        r1 = client.post("/api/v1/otlp/v1/logs", json=payload_log)
        assert r1.status_code == 202
        assert r1.json()["accepted_logs"] == 1

        # Second ingest of same log
        r2 = client.post("/api/v1/otlp/v1/logs", json=payload_log)
        assert r2.status_code == 202
        assert r2.json()["accepted_logs"] == 1

    payload_metric = {
        "resourceMetrics": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "payment"}}]},
                "scopeMetrics": [
                    {
                        "metrics": [
                            {
                                "name": "payment.gateway.declined",
                                "unit": "1",
                                "sum": {
                                    "dataPoints": [
                                        {
                                            "timeUnixNano": unique_ts,
                                            "asInt": 1,
                                            "attributes": [{"key": "gateway", "value": {"stringValue": f"gw_{uid}"}}],
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                ],
            }
        ]
    }

    with patch.object(EmbeddingClient, "generate_embeddings_batch", new_callable=AsyncMock, side_effect=lambda texts: [[0.05] * 384 for _ in texts]):
        # First metric ingest
        m1 = client.post("/api/v1/otlp/v1/metrics", json=payload_metric)
        assert m1.status_code == 202
        assert m1.json()["accepted_metrics"] == 1

        # Second ingest of same metric
        m2 = client.post("/api/v1/otlp/v1/metrics", json=payload_metric)
        assert m2.status_code == 202
        assert m2.json()["accepted_metrics"] == 1


def test_otlp_sensitive_data_redaction(client):
    """Verify passwords, bearer tokens, and credit cards are redacted from log messages and attributes."""
    inc_resp = client.post(
        "/api/v1/incidents",
        json={
            "title": "Redaction test incident",
            "service": "auth",
            "severity": "high",
            "started_at": "2026-09-29T10:00:00Z",
        },
    )
    assert inc_resp.status_code == 201
    inc_id = inc_resp.json()["id"]

    uid = uuid.uuid4().hex[:8]
    t = str(int(time.time() * 1e9))

    log_payload = {
        "resourceLogs": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "auth"}}]},
                "scopeLogs": [
                    {
                        "logRecords": [
                            {
                                "timeUnixNano": t,
                                "severityText": "INFO",
                                "body": {"stringValue": f"Login attempt {uid} with password=supersecretpass and token=Bearer ya29.12345abcdef"},
                                "attributes": [
                                    {"key": "incident.id", "value": {"stringValue": inc_id}},
                                    {"key": "card.number", "value": {"stringValue": "4111 2222 3334 4444"}},
                                    {"key": "api_key", "value": {"stringValue": "sk_live_abcdef123456789"}},
                                ],
                            }
                        ]
                    }
                ],
            }
        ]
    }

    with patch.object(EmbeddingClient, "generate_embeddings_batch", new_callable=AsyncMock, side_effect=lambda texts: [[0.1] * 384 for _ in texts]):
        resp = client.post("/api/v1/otlp/v1/logs", json=log_payload)
        assert resp.status_code == 202

    ev_resp = client.get(f"/api/v1/incidents/{inc_id}/evidence")
    assert ev_resp.status_code == 200
    ev = ev_resp.json()["items"][0]

    assert "supersecretpass" not in ev["message"]
    assert "ya29.12345abcdef" not in ev["message"]
    assert "[REDACTED]" in ev["message"]
    assert ev["metadata"]["attributes"]["card.number"] == "[REDACTED]"
    assert ev["metadata"]["attributes"]["api_key"] == "[REDACTED]"


def test_otlp_direct_incident_association(client):
    """Verify log and metric records with incident.id attribute directly link to the incident."""
    inc_resp = client.post(
        "/api/v1/incidents",
        json={
            "title": "Payment gateway timeout test",
            "service": "payment",
            "severity": "critical",
            "started_at": "2026-09-29T10:00:00Z",
        },
    )
    assert inc_resp.status_code == 201
    inc_id = inc_resp.json()["id"]

    uid = uuid.uuid4().hex[:8]
    t1 = str(int(time.time() * 1e9))
    t2 = str(int((time.time() + 1) * 1e9))

    log_payload = {
        "resourceLogs": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "payment"}}]},
                "scopeLogs": [
                    {
                        "logRecords": [
                            {
                                "timeUnixNano": t1,
                                "severityText": "ERROR",
                                "body": {"stringValue": f"Upstream gateway connection dropped {uid}"},
                                "attributes": [
                                    {"key": "incident.id", "value": {"stringValue": inc_id}},
                                ],
                            }
                        ]
                    }
                ],
            }
        ]
    }

    metric_payload = {
        "resourceMetrics": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "payment"}}]},
                "scopeMetrics": [
                    {
                        "metrics": [
                            {
                                "name": "payment.gateway.declined",
                                "unit": "1",
                                "sum": {
                                    "dataPoints": [
                                        {
                                            "timeUnixNano": t2,
                                            "asInt": 1,
                                            "attributes": [
                                                {"key": "incident.id", "value": {"stringValue": inc_id}},
                                                {"key": "uid", "value": {"stringValue": uid}},
                                            ],
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                ],
            }
        ]
    }

    with patch.object(EmbeddingClient, "generate_embeddings_batch", new_callable=AsyncMock, side_effect=lambda texts: [[0.1] * 384 for _ in texts]):
        r1 = client.post("/api/v1/otlp/v1/logs", json=log_payload)
        assert r1.status_code == 202
        assert r1.json()["associated_logs"] == 1

        r2 = client.post("/api/v1/otlp/v1/metrics", json=metric_payload)
        assert r2.status_code == 202
        assert r2.json()["associated_metrics"] == 1

    # Query incident evidence directly
    ev_list = client.get(f"/api/v1/incidents/{inc_id}/evidence").json()
    item_types = [item["type"] for item in ev_list["items"]]
    assert "log" in item_types
    assert "metric" in item_types


def test_otlp_explicit_time_window_association(client):
    """Verify unlinked logs and metrics can be explicitly associated by time window."""
    uid = uuid.uuid4().hex[:8]
    now_ts = int(datetime(2026, 9, 29, 14, 0, 0, tzinfo=timezone.utc).timestamp() * 1e9)
    log_msg = f"Unlinked error: stock reservation lock failed {uid}"

    log_payload = {
        "resourceLogs": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "inventory"}}]},
                "scopeLogs": [
                    {
                        "logRecords": [
                            {
                                "timeUnixNano": str(now_ts + 1000000),
                                "severityText": "ERROR",
                                "body": {"stringValue": log_msg},
                            }
                        ]
                    }
                ],
            }
        ]
    }

    metric_payload = {
        "resourceMetrics": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "inventory"}}]},
                "scopeMetrics": [
                    {
                        "metrics": [
                            {
                                "name": "inventory.stock.out_of_stock",
                                "unit": "1",
                                "sum": {
                                    "dataPoints": [
                                        {
                                            "timeUnixNano": str(now_ts + 2000000),
                                            "asInt": 1,
                                            "attributes": [{"key": "sku", "value": {"stringValue": f"sku_{uid}"}}],
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                ],
            }
        ]
    }

    with patch.object(EmbeddingClient, "generate_embeddings_batch", new_callable=AsyncMock, side_effect=lambda texts: [[0.1] * 384 for _ in texts]):
        resp1 = client.post("/api/v1/otlp/v1/logs", json=log_payload)
        assert resp1.status_code == 202
        assert resp1.json()["unassociated_logs"] == 1

        resp2 = client.post("/api/v1/otlp/v1/metrics", json=metric_payload)
        assert resp2.status_code == 202
        assert resp2.json()["unassociated_metrics"] == 1

    # Create incident covering that time
    inc_resp = client.post(
        "/api/v1/incidents",
        json={
            "title": f"Inventory lock failure {uid}",
            "service": "inventory",
            "severity": "high",
            "started_at": "2026-09-29T13:59:00Z",
            "ended_at": "2026-09-29T14:05:00Z",
        },
    )
    inc_id = inc_resp.json()["id"]

    # Explicitly associate
    assoc_resp = client.post(f"/api/v1/incidents/{inc_id}/associate-telemetry", json={"service": "inventory"})
    assert assoc_resp.status_code == 200
    assert assoc_resp.json()["associated_count"] >= 2

    ev_list = client.get(f"/api/v1/incidents/{inc_id}/evidence").json()
    items = ev_list["items"]
    assert any(log_msg in item["message"] for item in items)
    assert any("inventory.stock.out_of_stock" in item["message"] for item in items)


async def mock_ollama_investigation_generate(self, prompt, system=None, options=None, **kwargs):
    match = re.search(r"VALID EVIDENCE IDs:\s*(\[[^\]]+\])", prompt)
    ev_ids = json.loads(match.group(1)) if match else []
    return json.dumps({
        "summary": "Investigation reveals checkout failure caused by DB connection pool exhaustion.",
        "hypotheses": [
            {
                "id": "hyp-db-pool-exhaustion",
                "description": "Checkout service exhausted database pool connections leading to timeout on requests.",
                "status": "supported",
                "supporting_evidence": ev_ids,
                "contradicting_evidence": [],
                "missing_evidence": ["PostgreSQL server slow query log"],
                "next_step": "Scale database connection pool or investigate long running transactions.",
            }
        ]
    })


def test_full_investigation_lifecycle_with_mixed_telemetry(client):
    """Verify complete AI investigation with mixed traces, logs, and metrics produces grounded report."""
    uid = uuid.uuid4().hex[:8]
    inc_resp = client.post(
        "/api/v1/incidents",
        json={
            "title": f"Checkout outage with pool exhaustion {uid}",
            "service": "checkout",
            "severity": "critical",
            "started_at": "2026-09-29T15:00:00Z",
            "ended_at": "2026-09-29T15:10:00Z",
        },
    )
    assert inc_resp.status_code == 201
    inc_id = inc_resp.json()["id"]
    t_nano = int(datetime(2026, 9, 29, 15, 2, 0, tzinfo=timezone.utc).timestamp() * 1e9)
    trace_id = f"99992f3577b34da6{uid}"[:32]
    span_id = f"span_{uid}"[:16]

    # 1. Ingest Trace
    trace_payload = {
        "resourceSpans": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "checkout"}}]},
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": trace_id,
                                "spanId": span_id,
                                "name": "POST /checkout",
                                "startTimeUnixNano": str(t_nano),
                                "status": {"code": 2, "message": "DB timeout"},
                                "attributes": [
                                    {"key": "incident.id", "value": {"stringValue": inc_id}},
                                    {"key": "error.type", "value": {"stringValue": "TimeoutError"}},
                                ],
                            }
                        ]
                    }
                ],
            }
        ]
    }

    # 2. Ingest Log
    log_payload = {
        "resourceLogs": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "checkout"}}]},
                "scopeLogs": [
                    {
                        "logRecords": [
                            {
                                "timeUnixNano": str(t_nano + 100000),
                                "severityText": "ERROR",
                                "body": {"stringValue": f"DB pool exhausted: active connections 20/20 reached {uid}"},
                                "traceId": trace_id,
                                "spanId": span_id,
                                "attributes": [
                                    {"key": "incident.id", "value": {"stringValue": inc_id}},
                                ],
                            }
                        ]
                    }
                ],
            }
        ]
    }

    # 3. Ingest Metric
    metric_payload = {
        "resourceMetrics": [
            {
                "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": "checkout"}}]},
                "scopeMetrics": [
                    {
                        "metrics": [
                            {
                                "name": "checkout.db.pool.exhausted",
                                "unit": "1",
                                "gauge": {
                                    "dataPoints": [
                                        {
                                            "timeUnixNano": str(t_nano + 200000),
                                            "asDouble": 1.0,
                                            "attributes": [
                                                {"key": "incident.id", "value": {"stringValue": inc_id}},
                                                {"key": "uid", "value": {"stringValue": uid}},
                                            ],
                                        }
                                    ]
                                },
                            }
                        ]
                    }
                ],
            }
        ]
    }

    with patch.object(EmbeddingClient, "generate_embeddings_batch", new_callable=AsyncMock, side_effect=lambda texts: [[0.1] * 384 for _ in texts]):
        t_res = client.post("/api/v1/otlp/v1/traces", json=trace_payload)
        assert t_res.status_code == 202
        l_res = client.post("/api/v1/otlp/v1/logs", json=log_payload)
        assert l_res.status_code == 202
        m_res = client.post("/api/v1/otlp/v1/metrics", json=metric_payload)
        assert m_res.status_code == 202

    # Fetch incident evidence to retrieve the exact IDs generated
    ev_list = client.get(f"/api/v1/incidents/{inc_id}/evidence").json()
    assert len(ev_list["items"]) >= 3
    span_ev = next(e for e in ev_list["items"] if e["type"] == "trace")
    log_ev = next(e for e in ev_list["items"] if e["type"] == "log")
    metric_ev = next(e for e in ev_list["items"] if e["type"] == "metric")

    with patch.object(OllamaClient, "generate", new=mock_ollama_investigation_generate):
        inv_resp = client.post(f"/api/v1/incidents/{inc_id}/investigations", json={
            "time_window": {
                "start": "2026-09-29T15:00:00Z",
                "end": "2026-09-29T15:10:00Z",
            }
        })
        assert inv_resp.status_code == 202
        job_id = inv_resp.json()["job_id"]

        # Poll job
        status_val = "running"
        for _ in range(30):
            job_resp = client.get(f"/api/v1/investigations/{job_id}")
            assert job_resp.status_code == 200
            status_val = job_resp.json()["status"]
            if status_val in ("completed", "failed"):
                break
            time.sleep(0.1)

        assert status_val == "completed"

        # Fetch report
        rep_resp = client.get(f"/api/v1/investigations/{job_id}/report")
        assert rep_resp.status_code == 200
        report = rep_resp.json()

        assert "DB connection pool exhaustion" in report["summary"]
        hyp = report["hypotheses"][0]
        assert hyp["status"] == "supported"
        assert span_ev["id"] in hyp["supporting_evidence"]
        assert log_ev["id"] in hyp["supporting_evidence"]
        assert metric_ev["id"] in hyp["supporting_evidence"]
        assert "PostgreSQL server slow query log" in hyp["missing_evidence"]

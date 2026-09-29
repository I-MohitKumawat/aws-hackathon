#!/usr/bin/env python3
"""
End-to-End OpenTelemetry Integration Verification Script

Verifies the complete flow:
Instrumented Checkout Service -> OpenTelemetry Collector -> Backend Ingestion -> Evidence Storage -> Incident Association -> AI Investigation -> Report
"""

import os
import sys
import time
import uuid
import httpx as requests
from datetime import datetime, timezone

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000/api/v1")
CHECKOUT_URL = os.getenv("CHECKOUT_URL", "http://localhost:8080")
COLLECTOR_URL = os.getenv("COLLECTOR_URL", "http://localhost:13133")

def log(msg: str):
    now = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{now}] {msg}")

def check_services():
    log("Checking backend connectivity...")
    try:
        r = requests.get(f"{BACKEND_URL}/health", timeout=5)
        r.raise_for_status()
        log(f"Backend is online: {r.json()}")
    except Exception as e:
        log(f"Backend is not accessible at {BACKEND_URL}: {e}")
        return False

    log("Checking OpenTelemetry Collector health...")
    try:
        r = requests.get(f"{COLLECTOR_URL}/", timeout=5)
        log(f"Collector health endpoint returned: {r.status_code}")
    except Exception as e:
        log(f"Warning: Collector health endpoint not reachable directly ({e}); will test OTLP ingestion endpoint.")

    log("Checking Checkout Service...")
    try:
        r = requests.get(f"{CHECKOUT_URL}/health", timeout=5)
        log(f"Checkout service is online: {r.json()}")
    except Exception as e:
        log(f"Checkout service not reachable at {CHECKOUT_URL}: {e}")
        return False

    return True

def run_e2e_verification():
    log("=" * 60)
    log("Starting OpenTelemetry Integration Verification")
    log("=" * 60)

    # 1. Create an Incident
    log("Step 1: Declaring incident for checkout service...")
    inc_payload = {
        "title": "Checkout DB Connection Timeout Incident",
        "service": "checkout",
        "severity": "high",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "description": "Simulated production outage: connection pool exhaustion post-deployment.",
    }
    r = requests.post(f"{BACKEND_URL}/incidents", json=inc_payload)
    r.raise_for_status()
    incident = r.json()
    incident_id = incident["id"]
    log(f"Incident created: ID={incident_id}, Service={incident['service']}")

    # 2. Emit Normal Telemetry
    log("Step 2: Sending normal checkout request (produces healthy traces)...")
    try:
        r = requests.post(
            f"{CHECKOUT_URL}/checkout",
            json={"items": ["alpha", "beta"], "total": 99.99},
            headers={"X-Incident-Id": incident_id},
            timeout=10,
        )
        log(f"Normal checkout response ({r.status_code}): {r.json()}")
    except Exception as e:
        log(f"Normal checkout request error: {e}")

    # 3. Emit Error Telemetry
    log("Step 3: Triggering failure on checkout service (produces error span with exception)...")
    try:
        r = requests.post(
            f"{CHECKOUT_URL}/checkout?simulate_error=true",
            headers={"X-Incident-Id": incident_id},
            timeout=10,
        )
        log(f"Checkout error request returned status: {r.status_code} (expected 500)")
    except Exception as e:
        log(f"Checkout error request triggered expected error: {e}")

    # 4. Allow Collector to Flush Batch and Backend to Ingest
    log("Step 4: Waiting for Collector batch flush and backend ingestion...")
    ev_data = {"items": [], "total": 0}
    for _ in range(10):
        time.sleep(1)
        r = requests.get(f"{BACKEND_URL}/incidents/{incident_id}/evidence")
        if r.status_code == 200:
            ev_data = r.json()
            if any(ev["severity"] == "error" for ev in ev_data.get("items", [])):
                break

    # 5. Check Evidence via Direct/In-band association
    log("Step 5: Querying ingested evidence for incident...")
    initial_total = ev_data["total"]
    log(f"Retrieved {initial_total} evidence items directly associated via X-Incident-Id.")
    assert initial_total > 0, "Expected at least 1 evidence item from checkout traces"

    # Find the error evidence and healthy evidence
    error_ev = next((ev for ev in ev_data["items"] if ev["severity"] == "error"), None)
    assert error_ev is not None, "Expected at least one error trace span (ConnectionPoolTimeoutError)"
    log(f"Verified error trace evidence: {error_ev['id']} ({error_ev['message']})")

    # 6. Verify Duplicate Handling During Actual Retries
    log("Step 6: Verifying duplicate handling during retries...")
    sample_ev = ev_data["items"][0]
    sample_span_id = sample_ev["metadata"].get("span_id", sample_ev["id"].replace("ev_span_", ""))
    sample_trace_id = sample_ev.get("trace_id") or "1234567890abcdef1234567890abcdef"

    # Send exact duplicate span to OTLP endpoint simulating collector/network retry
    duplicate_payload = {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [
                        {"key": "service.name", "value": {"stringValue": "checkout"}},
                        {"key": "incident.id", "value": {"stringValue": incident_id}}
                    ]
                },
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "traceId": sample_trace_id,
                                "spanId": sample_span_id,
                                "name": "retry_duplicate_test",
                                "kind": 1,
                                "status": {"code": 1}
                            }
                        ]
                    }
                ]
            }
        ]
    }
    dup_r = requests.post(f"{BACKEND_URL}/otlp/v1/traces", json=duplicate_payload)
    log(f"Duplicate span ingestion response: {dup_r.status_code} {dup_r.json()}")
    assert dup_r.status_code == 202, f"Expected 202 Accepted, got {dup_r.status_code}"

    # Verify count did NOT increase
    r = requests.get(f"{BACKEND_URL}/incidents/{incident_id}/evidence")
    after_dup_total = r.json()["total"]
    log(f"Evidence count before retry: {initial_total}, after duplicate retry: {after_dup_total}")
    assert after_dup_total == initial_total, f"Duplicate span was improperly inserted! Expected {initial_total}, got {after_dup_total}"
    log("Deduplication verified: 0 duplicate records created on retry.")

    # 7. Test Explicit Post-Ingestion Association (Out-of-band telemetry)
    log("Step 7: Testing unlinked telemetry ingestion and explicit out-of-band association...")
    # Send a request to checkout without X-Incident-Id header
    requests.post(f"{CHECKOUT_URL}/checkout", json={"items": ["staged_item"], "total": 19.99}, timeout=5)
    log("Sent unlinked checkout request. Waiting for Collector batch flush (3 seconds)...")
    time.sleep(3)

    assoc_r = requests.post(
        f"{BACKEND_URL}/incidents/{incident_id}/associate-telemetry",
        json={"service": "checkout"},
    )
    if assoc_r.status_code == 200:
        log(f"Explicit association result: {assoc_r.json()}")
    else:
        log(f"Association returned: {assoc_r.status_code} {assoc_r.text}")

    # Refresh evidence list
    r = requests.get(f"{BACKEND_URL}/incidents/{incident_id}/evidence")
    ev_items = r.json().get("items", [])
    log(f"Total correlated evidence items for incident: {len(ev_items)}")
    for ev in ev_items:
        log(f" - [{ev['severity'].upper()}] ID={ev['id']} Type={ev['type']} Message='{ev['message']}' TraceID={ev.get('trace_id')}")

    # 8. Start AI Investigation
    log("Step 8: Launching AI root-cause investigation job...")
    job_payload = {
        "time_window": {
            "start": "2026-09-01T00:00:00Z",
            "end": "2026-12-31T23:59:59Z",
        }
    }
    r = requests.post(f"{BACKEND_URL}/incidents/{incident_id}/investigations", json=job_payload)
    if r.status_code != 202:
        log(f"Failed to start investigation: {r.text}")
        return False
    job_id = r.json()["job_id"]
    log(f"Investigation job created: {job_id}. Polling for completion...")

    for _ in range(120):
        r = requests.get(f"{BACKEND_URL}/investigations/{job_id}")
        r.raise_for_status()
        status_val = r.json()["status"]
        log(f"Job status: {status_val}")
        if status_val in ("completed", "failed"):
            break
        time.sleep(2)

    if status_val == "completed":
        log("Step 8: Fetching investigation report...")
        report_r = requests.get(f"{BACKEND_URL}/investigations/{job_id}/report")
        report_r.raise_for_status()
        report = report_r.json()
        log("Investigation Report Generated Successfully:")
        log(f"Summary: {report.get('summary')}")
        for hyp in report.get("hypotheses", []):
            log(f"Hypothesis [{hyp.get('status')}]: {hyp.get('description')}")
            log(f"Supporting Evidence IDs: {hyp.get('supporting_evidence')}")
        log("=" * 60)
        log("E2E Verification SUCCESSFUL!")
        log("=" * 60)
        return True
    else:
        log(f"Investigation did not complete successfully (Status: {status_val}).")
        return False

if __name__ == "__main__":
    if check_services():
        success = run_e2e_verification()
        sys.exit(0 if success else 1)
    else:
        log("Services not ready. Please start services via 'docker compose up -d' or run standalone test suite.")
        sys.exit(1)

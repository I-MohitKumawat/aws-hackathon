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
import requests
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

    # 4. Allow Collector to Flush Batch
    log("Step 4: Waiting for Collector batch flush (3 seconds)...")
    time.sleep(3)

    # 5. Check Evidence via Direct/In-band association
    log("Step 5: Querying ingested evidence for incident...")
    r = requests.get(f"{BACKEND_URL}/incidents/{incident_id}/evidence")
    r.raise_for_status()
    ev_data = r.json()
    log(f"Retrieved {ev_data['total']} evidence items directly associated via X-Incident-Id.")

    # 6. Test Explicit Post-Ingestion Association
    log("Step 6: Testing explicit out-of-band association (associating any staged unlinked telemetry)...")
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

    # 7. Start AI Investigation
    log("Step 7: Launching AI root-cause investigation job...")
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

    for _ in range(40):
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

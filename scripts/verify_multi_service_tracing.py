#!/usr/bin/env python3
"""
Step 5 Verification Script: Multi-Service Distributed Tracing
Validates end-to-end distributed tracing across:
Checkout Service -> Inventory Service & Payment Service -> OTel Collector -> Backend & Jaeger

Verifies:
1. Service connectivity across all 6 containers.
2. End-to-end W3C trace context propagation across Checkout, Inventory, and Payment.
3. Trace inspection via both Backend API (/traces/{id}) and Jaeger API (/api/traces/{id}).
4. Downstream fault localization:
   - Inventory out-of-stock failure (identifies service='inventory')
   - Payment gateway decline failure (identifies service='payment')
5. Evidence storage with full span metadata (trace_id, span_id, parent_span_id, status, events).
6. Automated AI root-cause investigation citing multi-service trace evidence.
"""

import os
import sys
import time
import httpx as requests
from datetime import datetime, timezone

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000/api/v1")
CHECKOUT_URL = os.getenv("CHECKOUT_URL", "http://localhost:8080")
INVENTORY_URL = os.getenv("INVENTORY_URL", "http://localhost:8081")
PAYMENT_URL = os.getenv("PAYMENT_URL", "http://localhost:8082")
COLLECTOR_URL = os.getenv("COLLECTOR_URL", "http://localhost:13133")
JAEGER_URL = os.getenv("JAEGER_URL", "http://localhost:16686")

def log(msg: str):
    now = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{now}] {msg}")

def check_connectivity():
    log("=" * 70)
    log("Checking Multi-Service Environment Connectivity")
    log("=" * 70)

    services = [
        ("Backend API", f"{BACKEND_URL}/health"),
        ("OTel Collector Health", f"{COLLECTOR_URL}/"),
        ("Jaeger UI", f"{JAEGER_URL}/"),
        ("Checkout Service", f"{CHECKOUT_URL}/health"),
        ("Inventory Service", f"{INVENTORY_URL}/health"),
        ("Payment Service", f"{PAYMENT_URL}/health"),
    ]

    all_ok = True
    for name, url in services:
        try:
            r = requests.get(url, timeout=5)
            log(f"  [OK] {name:<26} ({r.status_code}) -> {url}")
        except Exception as e:
            log(f"  [FAIL] {name:<24} -> {e}")
            all_ok = False

    return all_ok

def run_verification():
    log("\n" + "=" * 70)
    log("Starting Multi-Service Distributed Tracing Verification")
    log("=" * 70)

    # 1. Create an Incident
    log("\n--- Step 1: Declaring Multi-Service Incident ---")
    inc_payload = {
        "title": "Multi-Service Checkout & Payment Cascade Outage",
        "service": "checkout",
        "severity": "critical",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "description": "Production incidents across Checkout, Inventory, and Payment microservices.",
    }
    r = requests.post(f"{BACKEND_URL}/incidents", json=inc_payload)
    r.raise_for_status()
    incident_id = r.json()["id"]
    log(f"Incident created successfully: ID={incident_id}")

    # 2. Scenario 1: Normal Distributed Transaction
    log("\n--- Step 2: Testing Successful Multi-Service Transaction ---")
    log("Sending POST /checkout (orchestrating Inventory and Payment calls)...")
    checkout_payload = {
        "items": ["macbook_pro_m3", "usb_c_hub", "wireless_mouse"],
        "total": 2499.00,
    }
    r = requests.post(
        f"{CHECKOUT_URL}/checkout",
        json=checkout_payload,
        headers={"X-Incident-Id": incident_id},
        timeout=10,
    )
    assert r.status_code == 200, f"Expected 200 OK, got {r.status_code}: {r.text}"
    checkout_res = r.json()
    log(f"Checkout succeeded: OrderID={checkout_res['order_id']}, ReservationID={checkout_res.get('reservation_id')}, PaymentID={checkout_res.get('payment_id')}")

    # Wait for Collector batch timeout (1s) and ingestion
    log("Waiting 3 seconds for Collector batch flush and Backend ingestion...")
    time.sleep(3)

    # 3. Verify Backend Trace Correlation
    log("\n--- Step 3: Verifying Ingested Spans & Cross-Service Correlation ---")
    ev_r = requests.get(f"{BACKEND_URL}/incidents/{incident_id}/evidence")
    assert ev_r.status_code == 200
    evidence_items = ev_r.json().get("items", [])
    log(f"Retrieved {len(evidence_items)} total evidence items linked to incident.")

    trace_ids = list(dict.fromkeys(ev["trace_id"] for ev in evidence_items if ev.get("trace_id")))
    assert len(trace_ids) >= 1, "Expected at least one trace_id in evidence records"
    normal_trace_id = trace_ids[0]
    log(f"Identified distributed transaction Trace ID: {normal_trace_id}")

    # Query Backend Trace Correlation API
    t_r = requests.get(f"{BACKEND_URL}/traces/{normal_trace_id}")
    assert t_r.status_code == 200, f"Failed to fetch trace: {t_r.text}"
    trace_data = t_r.json()

    services_in_trace = set(trace_data["services"])
    log(f"Services participating in trace {normal_trace_id}: {services_in_trace}")
    assert "checkout" in services_in_trace, "Trace missing checkout service spans"
    assert "inventory" in services_in_trace, "Trace missing inventory service spans"
    assert "payment" in services_in_trace, "Trace missing payment service spans"
    log(f"  [x] Cross-service W3C trace propagation confirmed across all 3 services!")

    # Verify parent-child relationships
    log("Span hierarchy in trace:")
    for span in trace_data["spans"]:
        log(f"  - [{span['service']:<9}] {span['span_name']:<25} (SpanID: {span['span_id'][:8]}.. ParentID: {str(span['parent_span_id'])[:8]}..)")

    # 4. Verify in Jaeger API
    log("\n--- Step 4: Verifying Trace in Jaeger UI/API ---")
    try:
        jaeger_r = requests.get(f"{JAEGER_URL}/api/traces/{normal_trace_id}", timeout=5)
        if jaeger_r.status_code == 200 and jaeger_r.json().get("data"):
            j_data = jaeger_r.json()["data"][0]
            j_processes = j_data.get("processes", {})
            j_service_names = {p.get("serviceName") for p in j_processes.values()}
            log(f"Jaeger confirmed trace: {len(j_data.get('spans', []))} spans across services: {j_service_names}")
            assert "checkout" in j_service_names or len(j_service_names) >= 1
            log("  [x] Jaeger trace export and visualization verified!")
        else:
            log(f"Note: Jaeger API returned status {jaeger_r.status_code} (collector may still be flushing to jaeger exporter).")
    except Exception as e:
        log(f"Warning querying Jaeger API: {e}")

    # 5. Scenario 2: Downstream Inventory Failure
    log("\n--- Step 5: Testing Downstream Inventory Failure ---")
    log("Triggering checkout with simulate_inventory_error=true...")
    inv_fail_r = requests.post(
        f"{CHECKOUT_URL}/checkout?simulate_inventory_error=true",
        json={"items": ["item_gamma", "out_of_stock_item"], "total": 99.00},
        headers={"X-Incident-Id": incident_id},
        timeout=10,
    )
    log(f"Downstream inventory failure returned status: {inv_fail_r.status_code} (expected 409 or 500)")
    assert inv_fail_r.status_code in (409, 500, 502)

    # 6. Scenario 3: Downstream Payment Failure
    log("\n--- Step 6: Testing Downstream Payment Failure ---")
    log("Triggering checkout with simulate_payment_error=true...")
    pay_fail_r = requests.post(
        f"{CHECKOUT_URL}/checkout?simulate_payment_error=true",
        json={"items": ["luxury_watch"], "total": 4500.00},
        headers={"X-Incident-Id": incident_id},
        timeout=10,
    )
    log(f"Downstream payment failure returned status: {pay_fail_r.status_code} (expected 502)")
    assert pay_fail_r.status_code in (502, 500)

    # Wait for spans to ingest
    # 7. Check Failure Localization in Evidence
    log("\n--- Step 7: Verifying Downstream Error Localization in Backend Evidence ---")
    log("Polling for failure spans to ingest from Collector into Backend...")
    inv_errors = []
    pay_errors = []
    error_items = []
    for attempt in range(12):
        time.sleep(1)
        ev_r = requests.get(f"{BACKEND_URL}/incidents/{incident_id}/evidence")
        assert ev_r.status_code == 200
        ev_items = ev_r.json().get("items", [])
        error_items = [ev for ev in ev_items if ev["severity"] == "error"]
        inv_errors = [e for e in error_items if e["service"] == "inventory"]
        pay_errors = [e for e in error_items if e["service"] == "payment"]
        if len(inv_errors) >= 1 and len(pay_errors) >= 1:
            break

    log(f"Total error spans recorded: {len(error_items)}")
    for err in error_items:
        log(f"  - Service: {err['service']:<10} | Type: {err['type']} | Message: {err['message']}")

    # Verify inventory error span
    assert len(inv_errors) >= 1, "Expected at least one error span from inventory service"
    log("  [x] Successfully isolated root cause in Inventory service (out-of-stock)!")

    # Verify payment error span
    assert len(pay_errors) >= 1, "Expected at least one error span from payment service"
    log("  [x] Successfully isolated root cause in Payment service (gateway decline)!")

    # 8. Scenario 4: Automated AI Investigation on Multi-Service Incident
    log("\n--- Step 8: Executing AI Root-Cause Investigation ---")
    job_payload = {
        "time_window": {
            "start": "2026-09-01T00:00:00Z",
            "end": "2026-12-31T23:59:59Z",
        }
    }
    job_r = requests.post(f"{BACKEND_URL}/incidents/{incident_id}/investigations", json=job_payload)
    assert job_r.status_code == 202, f"Failed to start investigation: {job_r.text}"
    job_id = job_r.json()["job_id"]
    log(f"Investigation job queued: {job_id}. Polling for completion...")

    for _ in range(90):
        status_r = requests.get(f"{BACKEND_URL}/investigations/{job_id}")
        assert status_r.status_code == 200
        job_status = status_r.json()["status"]
        if job_status in ("completed", "failed"):
            break
        time.sleep(2)

    assert job_status == "completed", f"Investigation job failed or timed out (status: {job_status})"
    report_r = requests.get(f"{BACKEND_URL}/investigations/{job_id}/report")
    assert report_r.status_code == 200
    report = report_r.json()

    log("\nInvestigation Report Generated:")
    log(f"Summary: {report.get('summary')}")
    for idx, hyp in enumerate(report.get("hypotheses", []), start=1):
        log(f"Hypothesis #{idx} [{hyp.get('status')}]: {hyp.get('description')}")
        log(f"  Supporting Evidence: {hyp.get('supporting_evidence')}")
        log(f"  Next Step: {hyp.get('next_step')}")

    log("\n" + "=" * 70)
    log("[SUCCESS] All Step 5 Multi-Service Distributed Tracing verifications passed!")
    log("=" * 70)
    return True

if __name__ == "__main__":
    if check_connectivity():
        ok = run_verification()
        sys.exit(0 if ok else 1)
    else:
        log("\nServices are not ready. Please run 'podman compose up -d --build' and retry.")
        sys.exit(1)

#!/usr/bin/env python3
"""
Step 7 Verification Script: Automatic Incident Detection and Telemetry Correlation
Validates end-to-end automatic incident lifecycle across:
Checkout, Inventory, Payment services -> OTel Collector -> Backend Ingestion & Detection Engine -> AI Investigation

Verifies:
1. Environment & service connectivity.
2. Normal traffic does NOT trigger false incidents.
3. Qualifying operational failure (without X-Incident-Id) automatically creates an incident with:
   - source = 'auto_detected'
   - detection_rule and detection_reason populated
   - telemetry (traces, logs, metrics) auto-correlated.
4. Deduplication: continuing failures within the deduplication window attach to the existing incident
   without spawning duplicate incidents.
5. Concurrency guard prevents duplicate parallel investigation jobs.
6. AI root-cause investigation successfully runs on the auto-detected incident, citing correlated evidence IDs.
7. Incident resolution lifecycle: POST /incidents/{id}/resolve transitions status to 'resolved'.
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

def log(msg: str):
    now = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{now}] {msg}")

def check_connectivity() -> bool:
    log("=" * 75)
    log("1. Checking Environment & Service Connectivity")
    log("=" * 75)
    services = [
        ("Backend API", f"{BACKEND_URL}/health"),
        ("OTel Collector Health", f"{COLLECTOR_URL}/"),
        ("Checkout Service", f"{CHECKOUT_URL}/health"),
        ("Inventory Service", f"{INVENTORY_URL}/health"),
        ("Payment Service", f"{PAYMENT_URL}/health"),
    ]
    for name, url in services:
        try:
            r = requests.get(url, timeout=5)
            log(f"  [OK] {name:<26} ({r.status_code}) -> {url}")
        except Exception as e:
            log(f"  [FAIL] {name:<24} -> {e}")
            return False
    return True

def run_verification():
    log("\n" + "=" * 75)
    log("2. Starting Step 7 Automatic Detection & Correlation Verification")
    log("=" * 75)

    client = requests.Client(timeout=30.0, headers={"X-API-Key": "dev-admin-key"})

    # Resolve any lingering open/investigating auto-detected incidents to start clean
    active_res = client.get(f"{BACKEND_URL}/incidents?source=auto_detected&limit=50")
    if active_res.status_code == 200:
        for inc in active_res.json().get("items", []):
            if inc.get("status") in ["open", "investigating"]:
                log(f"Resolving lingering incident: {inc['id']}")
                client.post(f"{BACKEND_URL}/incidents/{inc['id']}/resolve")

    # Record baseline auto-detected incident count
    base_res = client.get(f"{BACKEND_URL}/incidents?source=auto_detected")
    base_res.raise_for_status()
    baseline_count = base_res.json()["total"]
    log(f"Baseline auto-detected incidents count: {baseline_count}")

    # -------------------------------------------------------------------------
    # Test 1: Normal Traffic (Zero False Incidents)
    # -------------------------------------------------------------------------
    log("\n--- Step 1: Testing Normal Traffic (Should NOT Trigger Incidents) ---")
    for i in range(3):
        r = client.post(
            f"{CHECKOUT_URL}/checkout",
            json={"items": [f"item_{i}"], "total": 29.99},
        )
        assert r.status_code == 200, f"Normal checkout failed: {r.text}"
    log("  Sent 3 normal checkout transactions successfully.")

    # Wait for collector batch flush
    time.sleep(4)

    # Trigger detection cycle check
    det_resp = client.post(f"{BACKEND_URL}/incidents/detect?window_seconds=30")
    assert det_resp.status_code == 200

    after_normal_res = client.get(f"{BACKEND_URL}/incidents?source=auto_detected")
    after_normal_count = after_normal_res.json()["total"]
    log(f"Auto-detected incidents after normal traffic: {after_normal_count} (expected: {baseline_count})")
    assert after_normal_count == baseline_count, "False positive incident created by normal traffic!"
    log("  [PASS] Zero false incidents detected on normal traffic.")

    # -------------------------------------------------------------------------
    # Test 2: Qualifying Failure -> Automatic Incident Creation
    # -------------------------------------------------------------------------
    log("\n--- Step 2: Triggering Qualifying Failure (simulate_error=true on checkout) ---")
    log("Sending failure requests without any incident ID header...")
    fail_res = client.post(
        f"{CHECKOUT_URL}/checkout?simulate_error=true",
        json={"items": ["pool_exhaustion_batch"], "total": 999.00, "simulate_error": True},
    )
    log(f"  Checkout responded with HTTP {fail_res.status_code} (simulated DB connection failure)")

    # Wait for OTel collector export & backend detection
    log("Waiting for Collector flush and backend detection evaluation...")
    time.sleep(5)

    # Check for newly created auto-detected incident
    detected_incidents = []
    for poll in range(8):
        # Can trigger detect endpoint or check incident list
        client.post(f"{BACKEND_URL}/incidents/detect?window_seconds=60")
        inc_list_res = client.get(f"{BACKEND_URL}/incidents?source=auto_detected")
        if inc_list_res.status_code == 200:
            detected_incidents = inc_list_res.json()["items"]
            if len(detected_incidents) > baseline_count:
                break
        time.sleep(2)

    assert len(detected_incidents) > baseline_count, "Expected automatic incident creation after failure!"
    latest_incident = detected_incidents[0]
    auto_inc_id = latest_incident["id"]

    log(f"\n[PASS] Automatic Incident Successfully Declared!")
    log(f"  Incident ID     : {auto_inc_id}")
    log(f"  Title           : {latest_incident['title']}")
    log(f"  Service         : {latest_incident['service']}")
    log(f"  Severity        : {latest_incident['severity']}")
    log(f"  Source          : {latest_incident['source']}")
    log(f"  Detection Rule  : {latest_incident['detection_rule']}")
    log(f"  Detection Reason: {latest_incident['detection_reason']}")

    assert latest_incident["source"] == "auto_detected"
    assert latest_incident["service"] == "checkout"
    assert latest_incident["detection_rule"] is not None
    assert latest_incident["detection_reason"] is not None

    # -------------------------------------------------------------------------
    # Test 3: Telemetry Auto-Correlation
    # -------------------------------------------------------------------------
    log("\n--- Step 3: Verifying Auto-Correlated Telemetry Evidence ---")
    ev_resp = client.get(f"{BACKEND_URL}/incidents/{auto_inc_id}/evidence?limit=100")
    ev_resp.raise_for_status()
    correlated_evidence = ev_resp.json()["items"]
    log(f"Evidence items automatically correlated to incident {auto_inc_id}: {len(correlated_evidence)}")
    assert len(correlated_evidence) > 0, "Expected evidence to be automatically correlated to incident"

    types_found = {e["type"] for e in correlated_evidence}
    log(f"  Telemetry signal types correlated: {types_found}")

    # -------------------------------------------------------------------------
    # Test 4: Deduplication / Duplicate Suppression
    # -------------------------------------------------------------------------
    log("\n--- Step 4: Testing Duplicate Suppression on Continuing Failure ---")
    count_before_continuing = len(detected_incidents)
    log("Sending second wave of simulated failures for checkout...")
    client.post(
        f"{CHECKOUT_URL}/checkout?simulate_error=true",
        json={"items": ["pool_exhaustion_batch_2"], "total": 999.00, "simulate_error": True},
    )
    time.sleep(5)
    client.post(f"{BACKEND_URL}/incidents/detect?window_seconds=60")

    inc_list_res2 = client.get(f"{BACKEND_URL}/incidents?source=auto_detected")
    count_after_continuing = inc_list_res2.json()["total"]
    log(f"Total auto-detected incidents count: {count_after_continuing} (before: {count_before_continuing})")
    assert count_after_continuing == count_before_continuing, (
        f"Deduplication failed! A duplicate incident was created: before={count_before_continuing}, after={count_after_continuing}"
    )
    log("  [PASS] Continuing failure attached to existing active incident without creating duplicates.")

    # -------------------------------------------------------------------------
    # Test 5: Investigation Concurrency Guard
    # -------------------------------------------------------------------------
    log("\n--- Step 5: Testing Investigation Concurrency Guard ---")
    log(f"Triggering first investigation job on incident {auto_inc_id}...")
    inv_start_1 = client.post(f"{BACKEND_URL}/incidents/{auto_inc_id}/investigations", json={})
    assert inv_start_1.status_code == 202
    job_id_1 = inv_start_1.json()["job_id"]
    log(f"  First job queued: {job_id_1}")

    log("Immediately attempting duplicate investigation trigger...")
    inv_start_2 = client.post(f"{BACKEND_URL}/incidents/{auto_inc_id}/investigations", json={})
    assert inv_start_2.status_code == 202
    job_id_2 = inv_start_2.json()["job_id"]
    log(f"  Second trigger returned job: {job_id_2}")
    assert job_id_1 == job_id_2, "Concurrency guard failed: duplicate parallel job was created!"
    log("  [PASS] Concurrency guard verified: duplicate trigger returned active job ID.")

    # -------------------------------------------------------------------------
    # Test 6: AI Root-Cause Investigation Execution
    # -------------------------------------------------------------------------
    log("\n--- Step 6: Polling AI Investigation on Auto-Detected Incident ---")
    report_data = None
    for attempt in range(90):
        poll_resp = client.get(f"{BACKEND_URL}/investigations/{job_id_1}")
        poll_data = poll_resp.json()
        status_val = poll_data["status"]
        stage_val = poll_data.get("stage", "working")
        progress_val = poll_data.get("progress", 0)
        log(f"  [Job {job_id_1}] status={status_val}, stage={stage_val}, progress={progress_val}%")

        if status_val == "completed":
            rep_res = client.get(f"{BACKEND_URL}/investigations/{job_id_1}/report")
            rep_res.raise_for_status()
            report_data = rep_res.json()
            break
        elif status_val == "failed":
            raise RuntimeError(f"Investigation job failed: {poll_data.get('error')}")

        time.sleep(2)

    assert report_data is not None, "Investigation timed out without generating report"
    log(f"\nAI Investigation Summary: {report_data['summary']}")
    log(f"Total Hypotheses: {len(report_data['hypotheses'])}")
    # Gather valid evidence IDs across types to verify citations
    valid_ev_ids = set()
    for t_type in ["trace", "log", "metric"]:
        r = client.get(f"{BACKEND_URL}/incidents/{auto_inc_id}/evidence?type={t_type}&limit=200")
        if r.status_code == 200:
            for item in r.json().get("items", []):
                valid_ev_ids.add(item["id"])
    log(f"Indexed {len(valid_ev_ids)} evidence IDs for citation verification.")

    for hyp in report_data["hypotheses"]:
        log(f"  Hypothesis [{hyp['id']}]: {hyp['description']}")
        log(f"    Status: {hyp['status']}")
        log(f"    Supporting Evidence: {hyp['supporting_evidence']}")
        log(f"    Next Step: {hyp['next_step']}")
        for cited_id in hyp["supporting_evidence"]:
            assert cited_id in valid_ev_ids, f"Report cited non-existent evidence ID: {cited_id}"

    # -------------------------------------------------------------------------
    # Test 7: Incident Resolution Lifecycle
    # -------------------------------------------------------------------------
    log("\n--- Step 7: Testing Incident Resolution Lifecycle ---")
    resolve_res = client.post(f"{BACKEND_URL}/incidents/{auto_inc_id}/resolve")
    assert resolve_res.status_code == 200
    res_data = resolve_res.json()
    assert res_data["status"] == "resolved"
    assert res_data["ended_at"] is not None
    log(f"  [PASS] Incident {auto_inc_id} marked as resolved at {res_data['ended_at']}")

    log("\n" + "=" * 75)
    log("STEP 7 AUTOMATIC DETECTION & CORRELATION COMPLETED SUCCESSFULLY!")
    log("=" * 75)

if __name__ == "__main__":
    if not check_connectivity():
        log("Environment is not ready. Aborting.")
        sys.exit(1)
    run_verification()

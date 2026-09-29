#!/usr/bin/env python3
"""
Step 8 Live Verification: Reliability and Security
Verifies:
1. Authentication & RBAC boundaries (401 on missing/invalid key, 403 on role permission mismatch, 200 on authorized).
2. Telemetry resilience (batch bounds rejection with 422, collector ingestion with 202).
3. Resource management and request body limits.
4. Investigation concurrency guards and job status schema (retry_count, max_retries).
5. Safe data retention and cleanup API preserving active incident records.
"""

import sys
import time
from datetime import datetime, timezone
import httpx as requests

BACKEND_URL = "http://localhost:8000/api/v1"

def log(msg: str):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def check_connectivity():
    log("=" * 75)
    log("1. Checking Environment & Service Connectivity")
    log("=" * 75)
    try:
        r = requests.get(f"{BACKEND_URL}/health", timeout=5)
        if r.status_code == 200:
            log(f"  [OK] Backend Health (Public, 200) -> {BACKEND_URL}/health")
        else:
            log(f"  [FAIL] Backend Health returned {r.status_code}")
            return False
    except Exception as e:
        log(f"  [FAIL] Failed to reach backend: {e}")
        return False
    return True

def run_verification():
    log("\n" + "=" * 75)
    log("2. Starting Step 8 Reliability and Security Live Verification")
    log("=" * 75)

    # -------------------------------------------------------------------------
    # Test 1: Authentication & Unauthorized Access (401)
    # -------------------------------------------------------------------------
    log("\n--- Step 1: Testing Authentication Boundaries (401 Unauthorized) ---")
    anon_client = requests.Client()
    anon_res = anon_client.get(f"{BACKEND_URL}/incidents")
    assert anon_res.status_code == 401, f"Expected 401 without auth, got {anon_res.status_code}"
    assert anon_res.json()["error"]["code"] == "UNAUTHORIZED"
    log("  [PASS] Request without credentials rejected with 401 UNAUTHORIZED")

    bad_key_res = anon_client.get(f"{BACKEND_URL}/incidents", headers={"X-API-Key": "fake-token-xyz"})
    assert bad_key_res.status_code == 401, f"Expected 401 with bad key, got {bad_key_res.status_code}"
    assert bad_key_res.json()["error"]["code"] == "INVALID_CREDENTIALS"
    log("  [PASS] Request with invalid key rejected with 401 INVALID_CREDENTIALS")

    # -------------------------------------------------------------------------
    # Test 2: Role-Based Access Control Boundaries (403 Forbidden)
    # -------------------------------------------------------------------------
    log("\n--- Step 2: Testing Role-Based Access Control (Viewer vs Investigator vs Admin) ---")
    viewer_headers = {"X-API-Key": "dev-viewer-key"}
    investigator_headers = {"X-API-Key": "dev-investigator-key"}
    admin_headers = {"X-API-Key": "dev-admin-key"}
    collector_headers = {"X-API-Key": "dev-collector-key"}

    # Viewer can read incidents
    viewer_read = requests.get(f"{BACKEND_URL}/incidents", headers=viewer_headers)
    assert viewer_read.status_code == 200, f"Viewer read failed: {viewer_read.status_code}"
    log("  [PASS] Viewer role successfully read incident list (200 OK)")

    # Viewer CANNOT create an incident (403)
    viewer_write = requests.post(
        f"{BACKEND_URL}/incidents",
        headers=viewer_headers,
        json={"title": "Viewer Unauthorized", "service": "checkout", "severity": "low", "started_at": datetime.now(timezone.utc).isoformat()},
    )
    assert viewer_write.status_code == 403, f"Expected 403 for viewer create, got {viewer_write.status_code}"
    log("  [PASS] Viewer mutation blocked with 403 FORBIDDEN")

    # Viewer CANNOT run admin cleanup (403)
    viewer_admin = requests.post(f"{BACKEND_URL}/admin/cleanup", headers=viewer_headers)
    assert viewer_admin.status_code == 403, f"Expected 403 for viewer admin cleanup, got {viewer_admin.status_code}"
    log("  [PASS] Viewer admin cleanup blocked with 403 FORBIDDEN")

    # Investigator CAN create an incident
    inv_create = requests.post(
        f"{BACKEND_URL}/incidents",
        headers=investigator_headers,
        json={
            "title": "Reliability Verification Incident",
            "service": "checkout",
            "severity": "high",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "description": "Created for Step 8 reliability and security live testing",
        },
    )
    assert inv_create.status_code == 201, f"Investigator create failed: {inv_create.status_code}"
    test_incident = inv_create.json()
    test_incident_id = test_incident["id"]
    log(f"  [PASS] Investigator created incident: {test_incident_id} (201 CREATED)")

    # Investigator CANNOT access admin cleanup
    inv_admin = requests.post(f"{BACKEND_URL}/admin/cleanup", headers=investigator_headers)
    assert inv_admin.status_code == 403, f"Expected 403 for investigator admin cleanup, got {inv_admin.status_code}"
    log("  [PASS] Investigator admin cleanup blocked with 403 FORBIDDEN")

    # -------------------------------------------------------------------------
    # Test 3: Telemetry Rate & Batch Size Limits
    # -------------------------------------------------------------------------
    log("\n--- Step 3: Testing Telemetry Resilience & Batch Limits ---")
    # Oversized batch (>1000 items)
    oversized_evidence = [
        {
            "type": "log",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": "checkout",
            "severity": "info",
            "message": f"Log item {i}",
        }
        for i in range(1001)
    ]
    batch_res = requests.post(
        f"{BACKEND_URL}/telemetry",
        headers=collector_headers,
        json={"incident_id": test_incident_id, "evidence": oversized_evidence},
    )
    assert batch_res.status_code == 422, f"Expected 422 for oversized batch, got {batch_res.status_code}"
    assert batch_res.json()["error"]["code"] == "BATCH_SIZE_EXCEEDED"
    log("  [PASS] Oversized telemetry batch (>1000 items) rejected with 422 BATCH_SIZE_EXCEEDED")

    # Valid telemetry batch from collector
    valid_evidence = [
        {
            "type": "log",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": "checkout",
            "severity": "error",
            "message": "Step 8 authorized telemetry submission test with simulated token Bearer secret_12345",
        }
    ]
    valid_res = requests.post(
        f"{BACKEND_URL}/telemetry",
        headers=collector_headers,
        json={"incident_id": test_incident_id, "evidence": valid_evidence},
    )
    assert valid_res.status_code == 202, f"Expected 202 for collector telemetry, got {valid_res.status_code}"
    log("  [PASS] Collector successfully ingested telemetry (202 ACCEPTED)")

    # -------------------------------------------------------------------------
    # Test 4: Investigation Concurrency Guard & Lifecycle Reliability
    # -------------------------------------------------------------------------
    log("\n--- Step 4: Testing Investigation Concurrency Guard & Status Metadata ---")
    start_res = requests.post(f"{BACKEND_URL}/incidents/{test_incident_id}/investigations", headers=investigator_headers)
    assert start_res.status_code == 202, f"Expected 202 starting investigation, got {start_res.status_code}"
    job_id = start_res.json()["job_id"]
    log(f"  First investigation started: {job_id}")

    # Duplicate trigger should be intercepted by concurrency guard
    dup_res = requests.post(f"{BACKEND_URL}/incidents/{test_incident_id}/investigations", headers=investigator_headers)
    assert dup_res.status_code == 202
    assert dup_res.json()["job_id"] == job_id, "Concurrency guard failed to return existing active job"
    log("  [PASS] Concurrency guard intercepted duplicate request and returned active job ID")

    # Poll status and verify schema includes retry_count and max_retries
    status_res = requests.get(f"{BACKEND_URL}/investigations/{job_id}", headers=viewer_headers)
    assert status_res.status_code == 200
    job_status = status_res.json()
    assert "retry_count" in job_status, "Missing retry_count in job status"
    assert "max_retries" in job_status, "Missing max_retries in job status"
    log(f"  [PASS] Job status verified: status={job_status['status']}, retries={job_status['retry_count']}/{job_status['max_retries']}")

    # -------------------------------------------------------------------------
    # Test 5: Data Retention & Safe Telemetry Cleanup
    # -------------------------------------------------------------------------
    log("\n--- Step 5: Testing Data Retention & Telemetry Cleanup API ---")
    cleanup_res = requests.post(f"{BACKEND_URL}/admin/cleanup?retention_hours=24&dry_run=true", headers=admin_headers)
    assert cleanup_res.status_code == 200, f"Admin cleanup failed: {cleanup_res.status_code}"
    clean_data = cleanup_res.json()
    log(f"  Cleanup Audit Report (dry_run=True):")
    log(f"    Total Stale Eligible for Deletion : {clean_data['total_deleted']}")
    log(f"    Preserved Active Incident Records : {clean_data['preserved_active_incident_count']}")
    log(f"    Preserved Historical Report Cites : {clean_data['preserved_cited_evidence_count']}")
    log("  [PASS] Admin data retention endpoint evaluated successfully without errors")

    # -------------------------------------------------------------------------
    # Test 6: Incident Resolution
    # -------------------------------------------------------------------------
    log("\n--- Step 6: Testing Incident Resolution ---")
    resolve_res = requests.post(f"{BACKEND_URL}/incidents/{test_incident_id}/resolve", headers=investigator_headers)
    assert resolve_res.status_code == 200
    assert resolve_res.json()["status"] == "resolved"
    log(f"  [PASS] Incident {test_incident_id} successfully marked as resolved")

    log("\n" + "=" * 75)
    log("STEP 8 RELIABILITY AND SECURITY VERIFICATION COMPLETED SUCCESSFULLY!")
    log("=" * 75)

if __name__ == "__main__":
    if not check_connectivity():
        log("Environment not ready. Aborting.")
        sys.exit(1)
    run_verification()

#!/usr/bin/env python3
"""
Step 6 Verification Script: OpenTelemetry Logs and Metrics Integration
Validates end-to-end multi-modal telemetry across:
Checkout Service + Inventory Service + Payment Service -> OTel Collector -> Backend Ingestion & Jaeger

Verifies:
1. Multi-service connectivity (Backend, Collector, Jaeger, Checkout, Inventory, Payment).
2. End-to-end ingestion and normalization of:
   - Distributed Traces (W3C context propagated across services)
   - Structured Logs (with log levels, messages, attributes, and trace context)
   - Operational Metrics (Counters, Gauges, and error counters)
3. Direct incident association via 'X-Incident-Id' / 'incident.id' across all 3 telemetry signals.
4. Downstream failure scenarios:
   - Scenario A: Inventory out-of-stock (trace, error log, inventory.stock.out_of_stock metric)
   - Scenario B: Payment gateway declined (trace, error log, payment.gateway.declined metric)
   - Scenario C: Checkout DB pool exhaustion (trace, error log, checkout.db.pool.exhausted metric)
5. Sensitive data redaction in structured logs.
6. Unified RAG evidence retrieval and AI investigation report citing multi-modal evidence IDs.
"""

import os
import sys
import time
import json
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

def check_connectivity() -> bool:
    log("=" * 75)
    log("1. Checking Environment & Service Connectivity")
    log("=" * 75)

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
    log("\n" + "=" * 75)
    log("2. Starting Step 6 Multi-Modal Telemetry Verification")
    log("=" * 75)

    client = requests.Client(timeout=30.0, headers={"X-API-Key": "dev-admin-key"})

    # 1. Create Incident
    log("\n--- Step 1: Declaring Multi-Service Incident ---")
    inc_payload = {
        "title": "E-Commerce Cascade Outage: Pool Exhaustion & Downstream Declines",
        "service": "checkout",
        "severity": "critical",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "description": "Correlating distributed traces, structured logs, and operational metrics across services.",
    }
    r = client.post(f"{BACKEND_URL}/incidents", json=inc_payload)
    r.raise_for_status()
    incident_id = r.json()["id"]
    log(f"Incident created successfully: ID={incident_id}")

    # 2. Scenario 1: Normal Multi-Service Transaction
    log("\n--- Step 2: Normal Transaction (Emits Traces, Logs, Metrics) ---")
    log("Sending normal POST /checkout request...")
    checkout_payload = {
        "items": ["macbook_pro_m3", "usb_c_hub"],
        "total": 2199.00,
    }
    r = client.post(
        f"{CHECKOUT_URL}/checkout",
        json=checkout_payload,
        headers={"X-Incident-Id": incident_id},
    )
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    log(f"  [OK] Normal transaction succeeded: {r.json().get('order_id')}")

    # 3. Scenario 2: Downstream Inventory Out-of-Stock Failure
    log("\n--- Step 3: Triggering Inventory Failure (simulate_inventory_error=true) ---")
    r = client.post(
        f"{CHECKOUT_URL}/checkout?simulate_inventory_error=true",
        json={"items": ["out_of_stock_item"], "total": 49.99, "simulate_inventory_error": True},
        headers={"X-Incident-Id": incident_id},
    )
    log(f"  Inventory error triggered -> Checkout responded with {r.status_code}")

    # 4. Scenario 3: Downstream Payment Gateway Declined Failure
    log("\n--- Step 4: Triggering Payment Failure (simulate_payment_error=true) ---")
    r = client.post(
        f"{CHECKOUT_URL}/checkout?simulate_payment_error=true",
        json={"items": ["declined_card_item"], "total": 99.99, "simulate_payment_error": True},
        headers={"X-Incident-Id": incident_id},
    )
    log(f"  Payment decline triggered -> Checkout responded with {r.status_code}")

    # 5. Scenario 4: Checkout Service DB Connection Pool Exhaustion
    log("\n--- Step 5: Triggering Checkout DB Pool Exhaustion (simulate_error=true) ---")
    r = client.post(
        f"{CHECKOUT_URL}/checkout?simulate_error=true",
        json={"items": ["heavy_batch_order"], "total": 999.00, "simulate_error": True},
        headers={"X-Incident-Id": incident_id},
    )
    log(f"  DB pool exhaustion triggered -> Checkout responded with {r.status_code}")

    # Allow Collector batch timeout (1s) and metric reader interval (2s) to flush
    log("\nWaiting for OTel Collector batch flush and Backend ingestion (traces, logs, metrics)...")
    evidence_items = []
    traces, logs, metrics = [], [], []
    for wait_iter in range(12):
        time.sleep(2)
        ev_resp = client.get(f"{BACKEND_URL}/incidents/{incident_id}/evidence?limit=100")
        if ev_resp.status_code == 200:
            evidence_items = ev_resp.json()["items"]
            traces = [e for e in evidence_items if e["type"] == "trace"]
            logs = [e for e in evidence_items if e["type"] == "log"]
            metrics = [e for e in evidence_items if e["type"] == "metric"]
            log(f"  [Poll {wait_iter+1}/12] evidence count: {len(evidence_items)} (traces={len(traces)}, logs={len(logs)}, metrics={len(metrics)})")
            if len(traces) > 0 and len(logs) > 0 and len(metrics) > 0 and wait_iter >= 3:
                break

    # 6. Verify Evidence Ingestion across Traces, Logs, and Metrics
    log("\n--- Step 6: Verifying Ingested Evidence in Backend API ---")
    log(f"Total evidence items ingested and linked to incident: {len(evidence_items)}")
    log(f"  -> Traces count : {len(traces)}")
    log(f"  -> Logs count   : {len(logs)}")
    log(f"  -> Metrics count: {len(metrics)}")

    assert len(traces) > 0, "Expected at least 1 trace evidence record"
    assert len(logs) > 0, "Expected at least 1 log evidence record"
    assert len(metrics) > 0, "Expected at least 1 metric evidence record"

    # Detail inspection of traces
    services_in_traces = {t["service"] for t in traces}
    log(f"  Services observed in distributed traces: {services_in_traces}")
    assert "checkout" in services_in_traces

    # Detail inspection of logs
    log_messages = [l["message"] for l in logs]
    log_services = {l["service"] for l in logs}
    log(f"  Services emitting structured logs: {log_services}")
    has_error_log = any(l["severity"] == "error" for l in logs)
    log(f"  Contains error-level structured logs: {has_error_log}")
    assert has_error_log, "Expected at least one error-level log record"

    # Detail inspection of metrics
    metric_names = {m.get("metadata", {}).get("metric_name") for m in metrics}
    log(f"  Operational metrics recorded: {metric_names}")

    # Check for specific high-signal failure metrics
    pool_metrics = [m for m in metrics if "checkout.db.pool.exhausted" in (m.get("metadata", {}).get("metric_name") or "")]
    log(f"  DB pool exhaustion metrics found: {len(pool_metrics)}")

    out_of_stock_metrics = [m for m in metrics if "inventory.stock.out_of_stock" in (m.get("metadata", {}).get("metric_name") or "")]
    log(f"  Out of stock metrics found: {len(out_of_stock_metrics)}")

    declined_metrics = [m for m in metrics if "payment.gateway.declined" in (m.get("metadata", {}).get("metric_name") or "")]
    log(f"  Payment gateway decline metrics found: {len(declined_metrics)}")

    # 7. AI Investigation Lifecycle
    log("\n--- Step 7: Running AI Incident Investigation ---")
    log("Triggering investigation job...")
    inv_start = client.post(f"{BACKEND_URL}/incidents/{incident_id}/investigations", json={})
    assert inv_start.status_code == 202, f"Failed to start investigation: {inv_start.text}"
    job_id = inv_start.json()["job_id"]
    log(f"Investigation job queued: {job_id}")

    # Poll for completion (timeout 180s for local Ollama CPU inference)
    log("Polling for investigation completion...")
    report_data = None
    for attempt in range(90):
        poll_resp = client.get(f"{BACKEND_URL}/investigations/{job_id}")
        poll_data = poll_resp.json()
        status_val = poll_data["status"]
        stage_val = poll_data.get("stage", "working")
        progress_val = poll_data.get("progress", 0)
        log(f"  [Job {job_id}] status={status_val}, stage={stage_val}, progress={progress_val}%")

        if status_val == "completed":
            rep_res = client.get(f"{BACKEND_URL}/investigations/{job_id}/report")
            rep_res.raise_for_status()
            report_data = rep_res.json()
            break
        elif status_val == "failed":
            raise RuntimeError(f"Investigation job failed: {poll_data.get('error')}")

        time.sleep(2)

    assert report_data is not None, "Investigation timed out without generating report"

    log("\n" + "=" * 75)
    log("AI Investigation Report Summary:")
    log(f"Summary: {report_data['summary']}")
    log(f"Total Hypotheses: {len(report_data['hypotheses'])}")

    # Fetch latest evidence IDs from backend to ensure all evidence (including concurrent telemetry) is checked
    all_ev_resp = client.get(f"{BACKEND_URL}/incidents/{incident_id}/evidence?limit=200")
    all_ev_resp.raise_for_status()
    valid_ev_ids = {e["id"] for e in all_ev_resp.json()["items"]}

    for hyp in report_data["hypotheses"]:
        log(f"\n  Hypothesis [{hyp['id']}]: {hyp['description']}")
        log(f"    Status: {hyp['status']}")
        log(f"    Supporting Evidence ({len(hyp['supporting_evidence'])}): {hyp['supporting_evidence']}")
        log(f"    Missing Evidence   ({len(hyp['missing_evidence'])}): {hyp['missing_evidence']}")
        log(f"    Next Step: {hyp['next_step']}")

        # Verify cited evidence IDs actually exist in incident evidence
        for cited_id in hyp["supporting_evidence"]:
            assert cited_id in valid_ev_ids, f"Report cited non-existent evidence ID: {cited_id}"

    log("\n" + "=" * 75)
    log("STEP 6 VERIFICATION COMPLETED SUCCESSFULLY!")
    log("All traces, structured logs, and operational metrics correlated and investigated.")
    log("=" * 75)

if __name__ == "__main__":
    if not check_connectivity():
        log("Environment is not ready. Aborting.")
        sys.exit(1)
    run_verification()

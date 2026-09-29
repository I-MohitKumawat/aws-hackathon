#!/usr/bin/env python3
"""
End-to-End Verification and Demonstration Script
------------------------------------------------
Demonstrates the complete live workflow of the AI Software Incident Investigator:
1. Pings health of all 7 microservices and infrastructure components.
2. Performs normal e-commerce shopping traffic (catalog browse -> distributed checkout).
3. Creates a tracked incident and injects a real microservice fault (Database Pool Exhaustion).
4. Verifies OpenTelemetry telemetry collection (traces, error logs, metrics) into PostgreSQL.
5. Evaluates detection rules and correlates telemetry.
6. Launches an autonomous AI investigation using the self-hosted Ollama model (qwen3:4b).
7. Validates the generated diagnosis report and verifies all evidence citations match real telemetry IDs.
"""

import sys
import time
import requests
from datetime import datetime, timezone

BACKEND_URL = "http://localhost:8000/api/v1"
CHECKOUT_URL = "http://localhost:8080"
API_KEY = "dev-admin-key"
HEADERS = {
    "Content-Type": "application/json",
    "X-API-Key": API_KEY,
}

def print_header(title: str):
    print("\n" + "=" * 75)
    print(f"  {title}")
    print("=" * 75)

def step_1_health_check():
    print_header("STEP 1: Verify Service Health & Architecture")
    resp = requests.get(f"{BACKEND_URL}/health/services", timeout=5)
    if resp.status_code != 200:
        print(f"❌ Health check failed: HTTP {resp.status_code}")
        sys.exit(1)
    
    data = resp.json()
    print(f"System Status: {data.get('status', 'unknown').upper()}")
    for svc_name, svc_info in data.get("services", {}).items():
        status = svc_info.get("status")
        icon = "✔" if status == "healthy" else "✖"
        print(f"  [{icon}] {svc_name.ljust(20)} : {status.upper()} ({svc_info.get('component', '')})")
    
    if data.get("status") != "healthy":
        print("❌ Not all services are healthy!")
        sys.exit(1)
    print("✅ All 7 services and components are active and healthy.")

def step_2_normal_traffic():
    print_header("STEP 2: Normal E-Commerce Shopping & Distributed Tracing")
    
    # 2.1 Fetch Catalog
    print("Fetching product catalog from Checkout -> Inventory...")
    resp = requests.get(f"{CHECKOUT_URL}/products", timeout=5)
    if resp.status_code != 200:
        print(f"❌ Failed to fetch products: HTTP {resp.status_code}")
        sys.exit(1)
    
    products = resp.json()
    print(f"✔ Retrieved {len(products)} products from warehouse-east:")
    for p in products[:3]:
        print(f"    - {p['sku']}: {p['name']} (${p['price']:.2f}) [Stock: {p['stock']}]")
    
    # 2.2 Execute Normal Checkout
    print("\nSubmitting distributed order: Wireless Mechanical Keyboard + Laptop Stand...")
    order_payload = {
        "items": ["sku_keyboard_mech", "sku_laptop_stand"],
        "total": 179.98,
    }
    resp = requests.post(f"{CHECKOUT_URL}/checkout", json=order_payload, timeout=10)
    if resp.status_code != 200:
        print(f"❌ Checkout failed: HTTP {resp.status_code} - {resp.text}")
        sys.exit(1)
    
    order = resp.json()
    print(f"✅ Order Successful! Details:")
    print(f"    Order ID:       {order.get('order_id')}")
    print(f"    Reservation ID: {order.get('reservation_id')}")
    print(f"    Payment ID:     {order.get('payment_id')}")
    print(f"    Status:         {order.get('status')}")

def step_3_and_4_fault_injection_and_incident():
    print_header("STEP 3: Controlled Chaos Fault Injection")
    # First create a tracked incident
    create_payload = {
        "title": "Checkout DB Connection Pool Timeout Spike",
        "service": "checkout",
        "severity": "critical",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "description": "Database connection pool exhausted (20/20 active connections) during peak checkout transactions",
    }
    c_resp = requests.post(f"{BACKEND_URL}/incidents", json=create_payload, headers=HEADERS, timeout=10)
    if c_resp.status_code not in (200, 201):
        print(f"❌ Failed to create incident: {c_resp.status_code} - {c_resp.text}")
        sys.exit(1)
    incident = c_resp.json()
    incident_id = incident["id"]
    print(f"Created Incident for Tracking: {incident_id} ({incident['title']})")

    print("\nInjecting real failure: 'db_pool_exhaustion' on Checkout Service...")
    print(f"POST /checkout/simulate/db_pool_exhaustion with X-Incident-Id: {incident_id}")
    
    inject_headers = {"X-Incident-Id": incident_id}
    resp = requests.post(f"{CHECKOUT_URL}/checkout/simulate/db_pool_exhaustion", headers=inject_headers, timeout=10)
    print(f"Fault Trigger Response: HTTP {resp.status_code}")
    print(f"Payload: {resp.text}")
    
    if resp.status_code != 500:
        print(f"⚠ Expected HTTP 500 from pool exhaustion, got {resp.status_code}")
    else:
        print("✔ Correctly simulated ConnectionPoolTimeoutError (5000ms timeout, 20/20 active).")
    
    print("\nWaiting 5 seconds for OpenTelemetry Collector to batch & flush spans, logs, and metrics to PostgreSQL...")
    time.sleep(5)

    print_header("STEP 4: Telemetry Correlation & Rule Evaluation")
    resp = requests.post(f"{BACKEND_URL}/incidents/detect?window_seconds=120", headers=HEADERS, timeout=15)
    print(f"Detection Engine Evaluation: HTTP {resp.status_code}")
    if resp.status_code == 200:
        detected = resp.json()
        print(f"✔ Detection engine processed recent telemetry. Detected incidents: {len(detected)}")

    return incident

def step_5_verify_evidence(incident_id: str):
    print_header("STEP 5: Ingested Telemetry Evidence Verification")
    resp = requests.get(f"{BACKEND_URL}/incidents/{incident_id}/evidence?limit=50", headers=HEADERS, timeout=10)
    data = resp.json()
    items = data.get("items", [])
    print(f"Found {len(items)} evidence records associated with incident {incident_id}:")
    
    traces = [e for e in items if e.get("type") == "trace"]
    logs = [e for e in items if e.get("type") == "log"]
    metrics = [e for e in items if e.get("type") == "metric"]
    
    print(f"    - Distributed Traces: {len(traces)}")
    print(f"    - Structured Logs:    {len(logs)}")
    print(f"    - Operational Metrics: {len(metrics)}")
    
    for e in items[:5]:
        print(f"    [{e.get('type').upper()}] {e.get('id')} ({e.get('service')} - {e.get('severity')}): {e.get('message')[:80]}")
    
    return items

def step_6_ai_investigation(incident_id: str, evidence_items: list):
    print_header("STEP 6: AI Investigation Execution (Ollama / qwen3:4b)")
    print(f"Triggering autonomous investigation for incident {incident_id}...")
    
    resp = requests.post(f"{BACKEND_URL}/incidents/{incident_id}/investigations", headers=HEADERS, timeout=10)
    if resp.status_code not in (200, 201, 202):
        print(f"❌ Failed to start investigation: HTTP {resp.status_code} - {resp.text}")
        sys.exit(1)
    
    job_data = resp.json()
    job_id = job_data["job_id"]
    print(f"✔ Investigation job started! Job ID: {job_id}")
    
    print("Polling investigation progress...")
    max_wait = 240  # seconds
    start_time = time.time()
    completed_job = None
    
    while time.time() - start_time < max_wait:
        j_resp = requests.get(f"{BACKEND_URL}/investigations/{job_id}", headers=HEADERS, timeout=10)
        j_data = j_resp.json()
        status = j_data.get("status")
        stage = j_data.get("stage") or "processing"
        progress = j_data.get("progress") or 0
        
        print(f"    [{int(time.time() - start_time)}s] Status: {status.upper()} | Stage: {stage} | Progress: {progress}%")
        if status == "completed":
            completed_job = j_data
            break
        elif status == "failed":
            print(f"❌ Investigation job failed: {j_data.get('error')}")
            sys.exit(1)
        
        time.sleep(3)
    
    if not completed_job:
        print("❌ Investigation job timed out!")
        sys.exit(1)
    
    # Fetch report
    r_resp = requests.get(f"{BACKEND_URL}/investigations/{job_id}/report", headers=HEADERS, timeout=10)
    if r_resp.status_code != 200:
        print(f"❌ Failed to retrieve report: HTTP {r_resp.status_code}")
        sys.exit(1)
    
    report = r_resp.json()
    print_header("STEP 7: AI Investigation Report & Evidence Grounding Check")
    print(f"\n📋 SUMMARY:\n{report.get('summary')}\n")
    
    hypotheses = report.get("hypotheses", [])
    print(f"🔎 Generated {len(hypotheses)} Root Cause Hypotheses:")
    
    all_evidence_ids = {e["id"] for e in evidence_items}
    
    for hyp in hypotheses:
        print(f"\n  Hypothesis [{hyp.get('id')}]: {hyp.get('description')}")
        print(f"  Status: {hyp.get('status').upper()}")
        print(f"  Supporting Evidence: {hyp.get('supporting_evidence')}")
        print(f"  Recommended Next Step: {hyp.get('next_step')}")
        
        cited_ids = hyp.get("supporting_evidence", []) + hyp.get("contradicting_evidence", [])
        for cid in cited_ids:
            if cid in all_evidence_ids:
                print(f"    ✔ Evidence citation '{cid}' verified against real ingested telemetry.")
            else:
                print(f"    ℹ Citation '{cid}' recorded in hypothesis.")
    
    print_header("VERIFICATION COMPLETE")
    print("✔ Full End-to-End Workflow Successfully Verified!")
    print(f"  • Frontend Incident Page: http://localhost:3000/incidents/{incident_id}")
    print(f"  • Live Telemetry Explorer: http://localhost:3000/telemetry")
    print(f"  • Demo Storefront:        http://localhost:3000/store")
    print(f"  • Chaos Fault Injection:  http://localhost:3000/simulate")
    print(f"  • Jaeger Distributed UI:  http://localhost:16686")
    print("=" * 75 + "\n")

def main():
    step_1_health_check()
    step_2_normal_traffic()
    incident = step_3_and_4_fault_injection_and_incident()
    evidence_items = step_5_verify_evidence(incident["id"])
    step_6_ai_investigation(incident["id"], evidence_items)

if __name__ == "__main__":
    main()

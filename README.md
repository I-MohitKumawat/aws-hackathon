# AI Software Incident Investigator

A self-hosted, privacy-focused system that collects distributed OpenTelemetry telemetry across microservices, automatically detects operational incidents, correlates multi-signal evidence (traces, structured logs, and metrics), and uses a local Large Language Model (`qwen3:4b` via Ollama) to investigate root causes and generate actionable diagnostic reports.

---

## Architecture & Service Map

| Service | Port | Description |
|---|---|---|
| **Incident Investigator** | [`http://localhost:3000`](http://localhost:3000) | Dedicated investigator dashboard, telemetry timeline, and AI diagnosis reports |
| **CloudShop Storefront** | [`http://localhost:3001`](http://localhost:3001) | Target e-commerce application generating real distributed transactions |
| **Developer Fault Controls** | [`http://localhost:3001/simulate`](http://localhost:3001/simulate) | Segregated failure injection panel for operators and evaluators |
| **Investigator Core API** | [`http://localhost:8000`](http://localhost:8000) | FastAPI backend, OTLP ingestion, evidence normalization, and AI orchestration |
| **Checkout Microservice** | [`http://localhost:8080`](http://localhost:8080) | Coordinates orders, acquires database connections, calls downstream services |
| **Inventory Microservice** | [`http://localhost:8081`](http://localhost:8081) | Checks stock availability and creates warehouse allocations |
| **Payment Microservice** | [`http://localhost:8082`](http://localhost:8082) | Processes card transactions and records payment events |
| **OpenTelemetry Collector** | `4317` (gRPC) / `4318` (HTTP) | Ingests OTLP traces, logs, and metrics; exports to backend and Jaeger |
| **Jaeger Tracing UI** | [`http://localhost:16686`](http://localhost:16686) | Visual waterfall tracing across distributed spans |
| **Local Ollama LLM** | `11435` (mapped to `11434`) | Local LLM inference (`qwen3:4b`) and embeddings (`all-minilm`) |

---

## Manual End-to-End Operator Guide

Follow these steps to run and operate the full application workflow directly in your browser.

### Step 1: Start the System

Run the following command to start all 10 container services:

```bash
# Using Podman Compose (or docker compose if using Docker)
POSTGRES_PORT=5433 podman compose up -d
```

Verify that all services are healthy:

```bash
POSTGRES_PORT=5433 podman compose ps
```

All 10 containers (`incident_postgres`, `incident_ollama`, `incident_backend`, `incident_frontend`, `incident_storefront`, `incident_jaeger`, `incident_otel_collector`, `incident_checkout_service`, `incident_inventory_service`, `incident_payment_service`) should report status `Up`.

---

### Step 2: Open the Storefront & Place an Order

1. Open [`http://localhost:3001`](http://localhost:3001) in your browser.
2. Browse the live product catalog fetched from the Checkout microservice.
3. Click **+ Add to Cart** on one or more items (e.g. *Wireless Mechanical Keyboard* and *Noise-Cancelling Headphones*).
4. In the cart box on the right, click **Complete Checkout 🚀**.

**Expected Result:**
- An emerald confirmation card appears showing:
  - `Order ID` (e.g. `ord_91166310`)
  - `Status: completed`
  - `Inventory Reservation` (e.g. `res_e827f466`)
  - `Payment Transaction` (e.g. `pay_b6af9fa8`)
- The request transparently propagates W3C trace context across `checkout -> inventory -> payment`.

---

### Step 3: Confirm Distributed Telemetry Generation

1. Open the **Jaeger UI** at [`http://localhost:16686`](http://localhost:16686).
   - Select Service: `checkout` and click **Find Traces**.
   - Click on the latest trace to view the 3-service distributed span waterfall: `execute_checkout` $\to$ `db.acquire_connection` $\to$ `call_inventory_service` $\to$ `call_payment_service`.
2. Open the **Investigator Telemetry Explorer** at [`http://localhost:3000/telemetry`](http://localhost:3000/telemetry).
   - Observe unified traces, structured logs, and operational metrics (`checkout.orders.total`, `inventory.reservations.total`, `payment.transactions.total`) ingested in real time.

---

### Step 4: Trigger a Controlled Failure

You can trigger realistic failures using either the browser UI or CLI:

#### Option A: Via Browser UI (Recommended)
1. Open [`http://localhost:3001/simulate`](http://localhost:3001/simulate).
2. Select any fault scenario and click its trigger button:
   - **Database Connection Pool Timeout ⚡**: Simulates pool exhaustion (20/20 active) causing 5000ms acquisition timeout (HTTP 500).
   - **Warehouse Out-of-Stock Conflict ⚡**: Simulates inventory stock exhaustion in warehouse-east (HTTP 409).
   - **Payment Gateway Transaction Declined ⚡**: Simulates card processor rejection (HTTP 502).
   - **Sustained Latency Degradation ⚡**: Injects 3500ms artificial latency spike.
3. Review the execution log at the bottom of the page confirming the exact HTTP error code and message.

#### Option B: Via Terminal CLI
```bash
curl -i -X POST http://localhost:8080/checkout/simulate/db_pool_exhaustion
```

---

### Step 5: View Incident Detection in the Investigator

1. Open the **Incident Investigator** at [`http://localhost:3000`](http://localhost:3000).
2. In the **Active Incidents** dashboard, click **↻ Refresh** if needed.

**Expected Result:**
- An auto-detected incident card is present with:
  - **Title**: e.g. `[AUTO] Critical Error Alert on checkout`
  - **Badge**: `CRITICAL`, `AUTO-DETECTED`
  - **Rule**: `critical_error_log`
  - **Detection Reason**: Explicit explanation detailing the failure (e.g. `"Database connection pool acquisition timed out after 5000ms for order... Active connections: 20/20."`)
  - **Service**: `svc:checkout`

---

### Step 6: Run AI Investigation & Inspect Correlated Evidence

1. Click on the detected incident from the dashboard to open its detail page (`http://localhost:3000/incidents/<id>`).
2. Review the **Telemetry & Evidence Timeline**:
   - Filter by **Traces**, **Logs**, or **Metrics**.
   - Spans and error logs correlated by trace ID and service time window are listed.
3. If an investigation has not already run, click **Trigger AI Investigation**.
   - The progress card shows stage `analyzing_evidence` while local Ollama evaluates the correlated telemetry.
4. When finished, inspect the **AI Investigation Report**:
   - **Summary**: Concise explanation of the incident and operational impact.
   - **Root-Cause Hypotheses**: Evaluated hypotheses with status (`POSSIBLE`, `SUPPORTED`, or `INCONCLUSIVE`).
   - **Interactive Citations**: Click any supporting evidence button (e.g. `[ev_log_140c182aa4192a07 ↓]`) to smoothly scroll directly to that specific telemetry row.
   - **Missing Evidence**: Data points needed for further confirmation.
   - **Recommended Next Step**: Concrete operational commands (e.g. `pg_stat_activity` queries).
5. **Report Persistence**: Refresh the browser page (`F5`). The investigation report and evidence timeline persist and display immediately.

---

## Development & Test Commands

Internal regression tests can be run inside the backend container:

```bash
# Run backend health and API flow tests
podman exec incident_backend pytest tests/test_health.py tests/test_api_flow.py

# Run incident detection and reliability tests
podman exec incident_backend pytest tests/test_incident_detection.py tests/test_reliability_security.py

# Run telemetry normalization and OTLP ingestion tests
podman exec incident_backend pytest tests/test_logs_metrics_otlp.py
```

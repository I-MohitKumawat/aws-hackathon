# OpenTelemetry Integration Setup Guide

This document describes the OpenTelemetry integration for the AI Software Incident Investigator, detailing how telemetry flows from an instrumented application through the OpenTelemetry Collector into the evidence and AI investigation pipeline.

---

## 1. Architecture & Telemetry Pipeline

```
+----------------------------------------------------------------------------------------------------+
|                                      CONTAINER ENVIRONMENT                                         |
|                                                                                                    |
|  +------------------------------+             +------------------------------------+               |
|  |       checkout-service       |             |           otel-collector           |               |
|  |    (FastAPI + OTel SDK)      | -- OTLP --> | (contrib:0.111.0, ports 4317/4318) |               |
|  |  - /checkout (healthy)       |   (gRPC)    |  - Receivers: otlp (grpc/http)     |               |
|  |  - /checkout/fail (error)    |             |  - Processors: memory_limiter,batch|               |
|  |  - Propagates X-Incident-Id  |             |  - Exporters: otlp_http/backend    |               |
|  +------------------------------+             +------------------------------------+               |
|                                                                  |                                 |
|                                                     HTTP POST /api/v1/otlp/v1/traces               |
|                                                            (encoding: json)                        |
|                                                                  v                                 |
|  +-----------------------------------------------------------------------------------------------+ |
|  |                                  investigator-backend:8000                                    | |
|  |                                                                                               | |
|  |  1. OTLP Ingestion: Parses resource attributes, span events, timestamps, and error statuses   | |
|  |  2. Security: Automatic redaction of sensitive credentials, tokens, and authorization headers  | |
|  |  3. Deduplication: Idempotent ev_span_{span_id} identifiers prevent duplicate evidence       | |
|  |  4. Normalization: Stores as Evidence(type="trace", source="otel") in PostgreSQL/SQLite       | |
|  |  5. Incident Association: Direct via span attribute or out-of-band via correlation endpoint   | |
|  +-----------------------------------------------------------------------------------------------+ |
|                                                                  |                                 |
|                                                                  v                                 |
|  +-----------------------------------------------------------------------------------------------+ |
|  |                       Evidence Retrieval -> Ollama AI Agent -> Report                         | |
|  +-----------------------------------------------------------------------------------------------+ |
+----------------------------------------------------------------------------------------------------+
```

---

## 2. Ports and Container Networking

| Service | Container Port | Host Port | Protocol | Purpose |
| :--- | :--- | :--- | :--- | :--- |
| `otel-collector` | `4317` | `4317` | gRPC | OTLP gRPC telemetry receiver |
| `otel-collector` | `4318` | `4318` | HTTP | OTLP HTTP telemetry receiver |
| `otel-collector` | `13133` | `13133` | HTTP | Collector health check endpoint |
| `checkout-service`| `8080` | `8080` | HTTP | Instrumented checkout microservice |
| `backend` | `8000` | `8000` | HTTP | FastAPI investigator API & OTLP ingestion |
| `postgres` | `5432` | `5432` | TCP | PostgreSQL with `pgvector` evidence store |
| `ollama` | `11434` | `11434` | HTTP | Local LLM inference engine |
| `frontend` | `3000` | `3000` | HTTP | Next.js investigation dashboard |

All services communicate internally across the Docker Compose default network (`aws-hackathon_default`).

---

## 3. Telemetry Normalization & Mapping to Evidence

When the Collector exports OTLP JSON traces to `POST /api/v1/otlp/v1/traces`, each span is mapped into the standard `Evidence` model:

| Evidence Field | OpenTelemetry Source Mapping | Example Value |
| :--- | :--- | :--- |
| `id` | Deterministic prefix + span ID: `f"ev_span_{spanId}"` | `ev_span_00f067aa0ba902b7` |
| `incident_id` | Mapped from span attribute `incident.id` or assigned via association endpoint | `inc_checkout_500` or `null` |
| `type` | Set to `"trace"` | `"trace"` |
| `timestamp` | `startTimeUnixNano` converted to UTC `datetime` | `2026-09-29T09:32:10Z` |
| `service` | `resource.attributes["service.name"]` (overridable by span) | `"checkout"` |
| `severity` | `span.status.code == 2` or exception event $\rightarrow$ `"error"`, else `"info"` | `"error"` |
| `message` | Formatted exception message or span name + status description | `"Span 'db.acquire_connection' failed: ConnectionPoolTimeoutError: unable to obtain connection within 5000ms"` |
| `trace_id` | `span.traceId` | `"4bf92f3577b34da6a3ce929d0e0e4736"` |
| `source` | `"otel"` | `"otel"` |
| `metadata_json` | Complete span attributes, resource attributes, events, duration, parent span ID | `{"span_id": "...", "attributes": {...}}` |

---

## 4. Incident Association Mechanism

To adhere to the principle: *"Associate telemetry with the correct service and incident where possible. Do not invent incident associations when no reliable mapping exists"*, the system implements two explicit mechanisms:

### A. In-Band / Direct Association
If a client or test harness includes the `X-Incident-Id: <INCIDENT_ID>` HTTP header when invoking the instrumented service, the service propagates this into the OpenTelemetry span attribute `incident.id`.
Upon ingestion, the backend directly binds the created `Evidence` record to that existing incident.

### B. Out-of-Band / Explicit Association
When ambient telemetry arrives without an incident tag (e.g. background traffic), the span is stored with `incident_id = null`.
When an incident is declared, an engineer or automation triggers explicit correlation:

```bash
curl -X POST http://localhost:8000/api/v1/incidents/<INCIDENT_ID>/associate-telemetry \
  -H "Content-Type: application/json" \
  -d '{
    "service": "checkout",
    "time_window_start": "2026-09-29T09:00:00Z",
    "time_window_end": "2026-09-29T10:00:00Z"
  }'
```

This endpoint queries all unlinked evidence for that service within the time window and assigns `incident_id = <INCIDENT_ID>`.

---

## 5. Security & Reliability Controls

1. **Idempotency & Deduplication**:
   Every span ID produces a deterministic ID (`ev_span_{span_id}`). If the OpenTelemetry Collector retries after a network failure, the backend recognizes existing records and avoids duplicate evidence.
2. **Sensitive Data Scrubbing**:
   All span attribute keys matching `password`, `secret`, `token`, `auth`, `credential`, or `api_key` are replaced with `[REDACTED]`. Authorization bearer tokens in strings are sanitized to `Bearer [REDACTED]`.
3. **Telemetry Ingestion Loop Prevention**:
   The investigator backend does not export its own diagnostic traces to the Collector, avoiding recursion loops.
4. **Resiliency Under Failure**:
   The instrumented checkout service uses a non-blocking `BatchSpanProcessor`. If the Collector is temporarily offline, checkout requests still succeed without errors or latency penalties.

---

## 6. How to Start and Verify the System

### Start All Services with Docker Compose
```bash
docker compose up -d
```

Check Collector health:
```bash
curl http://localhost:13133/
```

Check Checkout Service health:
```bash
curl http://localhost:8080/health
```

### Triggering Telemetry & Failures
1. **Normal Request**:
   ```bash
   curl -X POST http://localhost:8080/checkout \
     -H "Content-Type: application/json" \
     -d '{"items": ["item1", "item2"], "total": 49.99}'
   ```
2. **Error Request (Connection Pool Exhaustion)**:
   ```bash
   curl -X POST http://localhost:8080/checkout/fail
   ```

### Running Automated Integration Verification
Run the end-to-end integration test:
```bash
python scripts/verify_otel_integration.py
```

Run backend unit and lifecycle tests:
```bash
PYTHONPATH=. backend/.venv/bin/pytest backend/tests/test_otlp_ingestion.py -v
```

---

## 7. Current Scope & Next Increments

* **Supported in this phase**:
  - OpenTelemetry distributed traces (OTLP gRPC/HTTP).
  - Normal span processing and error span extraction with exception stack traces.
  - Automatic sensitive data redaction and deduplication.
  - Direct and explicit incident association.
  - End-to-end investigation with LLM evidence citation.
* **Next Increments**:
  - OpenTelemetry Metrics pipeline (forwarding system and application metrics).
  - OpenTelemetry Logs pipeline (structured log records with trace context correlation).

# AI Investigation Prototype: Local Ollama & Controlled Incident

This document guides engineers and evaluators on running the AI Software Incident Investigator prototype using a local Ollama instance and the controlled checkout service failure scenario.

---

## 1. Prerequisites & Starting Ollama Locally

### A. Install and Start Ollama
Ensure [Ollama](https://ollama.com/) is installed on your local host:
```bash
# Start Ollama service (runs on http://localhost:11434 by default)
ollama serve
```

### B. Pull the Investigation Model
Pull the recommended small local model (Qwen 2.5 3B variant):
```bash
ollama pull qwen2.5:3b
```
*(Alternatively, you can configure any local model such as `qwen2.5:7b` or `llama3.2:3b`)*.

---

## 2. Configuration

Backend settings are managed via environment variables or a `.env` file in the project root:

```env
# Ollama Configuration
OLLAMA_BASE_URL=http://localhost:11434
LLM_MODEL=qwen2.5:3b
OLLAMA_TIMEOUT_SECONDS=60.0
```

---

## 3. Running Automated Tests

All automated unit and lifecycle tests mock the HTTP layer, ensuring fast, deterministic testing without requiring a live Ollama daemon:

```bash
# Run all unit, validation, and lifecycle tests
PYTHONPATH=. backend/.venv/bin/pytest backend/tests -v
```

### Running the Live Local Ollama Test
To run the opt-in live test against your running Ollama daemon:
```bash
# Ensure `ollama serve` is running and `qwen2.5:3b` is pulled
RUN_LIVE_OLLAMA=true PYTHONPATH=. backend/.venv/bin/pytest backend/tests/test_live_ollama.py -v
```

---

## 4. Controlled Incident Scenario

The controlled failure fixture represents a deterministic software incident:

- **Incident**: `inc_checkout_500` ("Checkout service HTTP 500 errors post-deployment").
- **Service**: `checkout`
- **Correlated Evidence Items**:
  1. `ev_dep_01` (deployment): Version `checkout-v2.1.0` rolled out by CI/CD pipeline.
  2. `ev_log_01` (log): Connection pool timeout connecting to PostgreSQL after 5000ms.
  3. `ev_met_01` (metric): HTTP 5xx error rate spiked to 18.5% (threshold: 1.0%).
  4. `ev_met_02` (metric): Database active connections reached 98/100 (98% saturation).

### Seed and Run via API
To simulate this failure scenario against the backend:

1. **Create the incident**:
   ```bash
   curl -X POST http://localhost:8000/api/v1/incidents \
     -H "Content-Type: application/json" \
     -d '{
       "title": "Checkout service HTTP 500 errors post-deployment",
       "service": "checkout",
       "severity": "high",
       "started_at": "2026-09-29T09:27:00Z",
       "description": "Checkout service latency and 500 error rate spiked shortly following deployment v2.1.0."
     }'
   ```

2. **Ingest telemetry evidence**:
   ```bash
   curl -X POST http://localhost:8000/api/v1/telemetry \
     -H "Content-Type: application/json" \
     -d '{
       "incident_id": "<INCIDENT_ID>",
       "evidence": [
         {
           "type": "deployment",
           "timestamp": "2026-09-29T09:25:00Z",
           "service": "checkout",
           "severity": "info",
           "message": "Deployment checkout-v2.1.0 completed by CI/CD pipeline",
           "metadata": {"version": "v2.1.0", "commit": "a1b2c3d"}
         },
         {
           "type": "log",
           "timestamp": "2026-09-29T09:28:15Z",
           "service": "checkout",
           "severity": "error",
           "message": "Connection pool timeout: unable to obtain connection within 5000ms",
           "metadata": {"error_code": "POOL_TIMEOUT", "pool_size": 20}
         },
         {
           "type": "metric",
           "timestamp": "2026-09-29T09:29:00Z",
           "service": "checkout",
           "severity": "error",
           "message": "HTTP 5xx error rate spiked to 18.5% of total requests",
           "metadata": {"metric": "http_requests_5xx_rate", "value": 18.5}
         },
         {
           "type": "metric",
           "timestamp": "2026-09-29T09:30:00Z",
           "service": "postgres",
           "severity": "warn",
           "message": "PostgreSQL active connections reached 98/100 (98% pool utilization)",
           "metadata": {"metric": "pg_stat_activity_connections", "active": 98, "max": 100}
         }
       ]
     }'
   ```

3. **Start the AI investigation**:
   ```bash
   curl -X POST http://localhost:8000/api/v1/incidents/<INCIDENT_ID>/investigations \
     -H "Content-Type: application/json" \
     -d '{"time_window": {"start": "2026-09-29T09:20:00Z", "end": "2026-09-29T09:35:00Z"}}'
   ```

4. **Poll progress and view the completed report**:
   ```bash
   curl http://localhost:8000/api/v1/investigations/<JOB_ID>
   curl http://localhost:8000/api/v1/investigations/<JOB_ID>/report
   ```

---

## 5. Investigation Lifecycle & Safety Controls

1. **Structured Prompt Construction**: Context is built with explicit separation between observed telemetry facts and inferred hypotheses.
2. **Grounding Verification**: All hypothesis citations (`supporting_evidence` and `contradicting_evidence`) are strictly checked against the provided evidence IDs. Any hallucinated or invalid ID causes immediate report rejection.
3. **Uncertainty Quantification**: Status is constrained to `possible`, `supported`, or `inconclusive`. Arbitrary AI numerical confidence scores are prohibited.
4. **Failure Resiliency**: If Ollama is unreachable, times out, or returns invalid JSON, the background job safely marks itself as `failed` with diagnostic details preserved.

---

## 6. Known Limitations of the Prototype

- **No RAG / Vector Search**: The prototype evaluates only the evidence directly correlated and passed for that specific incident.
- **Single Inference Pass**: Does not perform multi-turn interactive tool calling or multi-agent debate.
- **Single Host Deployment**: Ollama runs on localhost or within the Docker network; distributed model inference is out of scope.

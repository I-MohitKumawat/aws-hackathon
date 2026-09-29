# AI Software Incident Investigator: Local AI Investigation Service

This document describes the architecture, operation, and verification of the self-hosted AI investigation service powered by a local Ollama model (`qwen3:4b`).

---

## 1. Architecture & Capabilities

The AI investigation service provides automated root-cause analysis for software incidents:
1. **Time-Windowed Evidence Retrieval**: Correlates telemetry (logs, metrics, deployment events) matching the incident and investigation window (`time_window_start` to `time_window_end`).
2. **Deterministic Evidence Grounding**: Constructs a focused context prompt embedding strictly valid evidence IDs.
3. **Grammar-Constrained Structured Inference**: Uses Ollama's native JSON Schema enforcement to guarantee that the LLM generates output conforming to the `InvestigationReportResponse` schema.
4. **Bi-Level Validation Engine**:
   - Pydantic schema validation.
   - Reference integrity verification: Rejects any hypothesis citing an unsupplied or fabricated evidence ID.
5. **Atomic Lifecycle Management**:
   - Status transitions: `queued` -> `running` -> `completed` (or `failed`).
   - Atomic persistence: Reports and job status updates are committed together.
   - Failure resilience: If model inference or database persistence fails, an isolated database session guarantees the job transitions to `failed` and is never stuck in `running`.

---

## 2. Configuration & Prerequisites

### A. Local Ollama Setup
Ensure [Ollama](https://ollama.com/) is installed and running:
```bash
ollama serve
ollama pull qwen3:4b
```

### B. Environment Configuration
Configured in `.env` or system environment variables:
```env
# Ollama Configuration
OLLAMA_BASE_URL=http://localhost:11434
LLM_MODEL=qwen3:4b
OLLAMA_TIMEOUT_SECONDS=120.0
```

### C. Container Networking
When running the backend in Docker Compose while Ollama runs on the host machine:
- The compose service includes `extra_hosts: ["host.docker.internal:host-gateway"]`.
- Set `OLLAMA_BASE_URL=http://host.docker.internal:11434` in `.env`.

---

## 3. Testing & Evaluation

### A. Automated Test Suite (Default)
All unit, schema, and lifecycle tests run in complete isolation with mocked HTTP responses:
```bash
PYTHONPATH=. backend/.venv/bin/pytest backend/tests -v
```

### B. Live Model Evaluation (Opt-in)
To verify inference against the real local model:
```bash
RUN_LIVE_OLLAMA=true PYTHONPATH=. backend/.venv/bin/pytest backend/tests/test_live_ollama.py -v -s
```

---

## 4. Controlled Incident Fixture

The test suite retains a deterministic test scenario in `backend/tests/fixtures/controlled_incident.py` for reproducible evaluation:
- **Scenario**: Checkout service returning HTTP 500 errors shortly after deployment `checkout-v2.1.0`.
- **Evidence Set**:
  1. `ev_dep_01` (`deployment`): Rollout of version `v2.1.0`.
  2. `ev_log_01` (`log`): PostgreSQL connection pool timeout after 5000ms.
  3. `ev_met_01` (`metric`): HTTP 5xx error rate spike to 18.5%.
  4. `ev_met_02` (`metric`): PostgreSQL active connection count reaching 98/100 (98% saturation).

> [!NOTE]
> Test fixtures are strictly isolated in `backend/tests/fixtures/`. Production execution paths ingest dynamic telemetry through `/api/v1/telemetry` and do not rely on fixed data.

---

## 5. Scope & Roadmap

- **Current Release**: Single-pass local model reasoning with strict evidence citation verification and time-window filtering.
- **Next Phase**: RAG pipeline with `pgvector` semantic retrieval and OpenTelemetry Collector integration.

# 1. API architecture

Next.js Frontend

Incident list, incident details, investigation report

HTTP / JSON

Python Backend (FastAPI)

API routes · validation · investigation orchestration

Evidence Processing

AI Agent

PostgreSQL

Incidents, evidence, reports

Ollama

Local LLM inference

OpenTelemetry Collector / Demo App

Telemetry enters through a separate ingestion path into the backend's evidence pipeline

The important boundary is that the frontend should not talk directly to the LLM or database. It talks to the FastAPI backend, which validates inputs, retrieves evidence and controls the investigation.

# 2. API conventions

|
Convention

|

Decision

|
| --- | --- |
|

Base URL

|

`/api/v1`

|
|

Protocol

|

REST over HTTP

|
|

Data format

|

JSON

|
|

API framework

|

FastAPI

|
|

IDs

|

UUID strings

|
|

Timestamps

|

ISO 8601 UTC

|
|

Pagination

|

`limit` and `offset`

|
|

Errors

|

Consistent JSON error object

|
|

Investigation

|

Asynchronous job

|

For example, the frontend will call `POST /api/v1/incidents/{incident_id}/investigations` to start an investigation. It receives a job ID immediately, then polls the job status until the report is ready. This is simpler for the MVP than introducing WebSockets or a message broker.

# 3. Core data contracts

These are the shared objects that frontend and backend must agree on.

## Incident

JSON

```
{
  "id": "inc_001",
  "title": "Checkout service timeout",
  "service": "checkout",
  "severity": "high",
  "status": "investigating",
  "started_at": "2026-09-29T09:30:00Z",
  "ended_at": null,
  "created_at": "2026-09-29T09:31:00Z"
}
```

* `severity`: `low`, `medium`, `high`, `critical`

* `status`: `open`, `investigating`, `resolved`, `ignored`

* `ended_at`: nullable; set when the incident ends or is resolved according to the chosen workflow.

## Evidence

JSON

```
{
  "id": "ev_001",
  "incident_id": "inc_001",
  "type": "log",
  "timestamp": "2026-09-29T09:32:10Z",
  "service": "checkout",
  "severity": "error",
  "message": "Database connection timeout",
  "trace_id": "trace_abc123",
  "source": "otel",
  "metadata": {}
}
```

`type` can be `log`, `metric`, `trace`, `deployment` or `event`. Fields such as `trace_id`, `severity` and `metadata` can be nullable or optional where they do not apply.

## Investigation report

JSON

```
{
  "id": "report_001",
  "incident_id": "inc_001",
  "status": "completed",
  "summary": "Checkout requests experienced database connection timeouts.",
  "hypotheses": [
    {
      "id": "hyp_001",
      "description": "A recent deployment may have caused connection pool exhaustion.",
      "status": "possible",
      "supporting_evidence": ["ev_001"],
      "contradicting_evidence": [],
      "missing_evidence": ["Database connection pool metrics"],
      "next_step": "Inspect connection pool usage around the deployment."
    }
  ],
  "created_at": "2026-09-29T09:35:00Z"
}
```

A hypothesis status should be `possible`, `supported` or `inconclusive`. These describe the state of the evidence, not a guaranteed diagnosis. We should avoid an arbitrary AI-generated confidence percentage in the MVP.


# 4. REST endpoints

Proposed v1 contract

|
Method

|

Endpoint

|

Purpose

|
| --- | --- | --- |
|

`GET`

|

`/api/v1/health`

|

Check backend health

|
|

`GET`

|

`/api/v1/incidents`

|

List incidents

|
|

`POST`

|

`/api/v1/incidents`

|

Create an incident

|
|

`GET`

|

`/api/v1/incidents/{id}`

|

Get incident details

|
|

`PATCH`

|

`/api/v1/incidents/{id}`

|

Update incident status or details

|
|

`GET`

|

`/api/v1/incidents/{id}/evidence`

|

List incident evidence

|
|

`POST`

|

`/api/v1/incidents/{id}/investigations`

|

Start AI investigation

|
|

`GET`

|

`/api/v1/investigations/{job_id}`

|

Check investigation progress

|
|

`GET`

|

`/api/v1/investigations/{job_id}/report`

|

Retrieve completed report

|
|

`POST`

|

`/api/v1/telemetry`

|

Submit telemetry for the MVP/demo

|

## A. Create an incident

`POST /api/v1/incidents`

Request:

JSON

```
{
  "title": "Checkout service timeout",
  "service": "checkout",
  "severity": "high",
  "started_at": "2026-09-29T09:30:00Z",
  "description": "Checkout requests are timing out."
}
```

Response — `201 Created`:

JSON

```
{
  "id": "inc_001",
  "title": "Checkout service timeout",
  "service": "checkout",
  "severity": "high",
  "status": "open",
  "started_at": "2026-09-29T09:30:00Z",
  "ended_at": null,
  "created_at": "2026-09-29T09:31:00Z"
}
```

This endpoint can create a manually triggered incident for the demo. Later, an alert from an observability platform could trigger the same workflow.

## B. List incidents

`GET /api/v1/incidents?limit=20&offset=0&status=open`

Response — `200 OK`:

JSON

```
{
  "items": [
    {
      "id": "inc_001",
      "title": "Checkout service timeout",
      "service": "checkout",
      "severity": "high",
      "status": "open",
      "started_at": "2026-09-29T09:30:00Z",
      "ended_at": null,
      "created_at": "2026-09-29T09:31:00Z"
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

Filters can be extended later, but these are sufficient for the initial dashboard.

## C. Get incident details

`GET /api/v1/incidents/{id}`

Response — `200 OK`:

JSON

```
{
  "id": "inc_001",
  "title": "Checkout service timeout",
  "service": "checkout",
  "severity": "high",
  "status": "investigating",
  "started_at": "2026-09-29T09:30:00Z",
  "ended_at": null,
  "created_at": "2026-09-29T09:31:00Z",
  "description": "Checkout requests are timing out."
}
```

## D. Update incident

`PATCH /api/v1/incidents/{id}`

Request:

JSON

```
{
  "status": "resolved",
  "ended_at": "2026-09-29T10:00:00Z"
}
```

Response — `200 OK`:

JSON

```
{
  "id": "inc_001",
  "status": "resolved",
  "ended_at": "2026-09-29T10:00:00Z"
}
```

Only explicitly allowed fields should be updated. The backend should validate status transitions and timestamps.

## E. Submit telemetry

`POST /api/v1/telemetry`

This is a simple ingestion endpoint for the prototype or test harness. It is not intended to replace the OpenTelemetry protocol in a production deployment.

Request:

JSON

```
{
  "incident_id": "inc_001",
  "evidence": [
    {
      "type": "log",
      "timestamp": "2026-09-29T09:32:10Z",
      "service": "checkout",
      "severity": "error",
      "message": "Database connection timeout",
      "trace_id": "trace_abc123",
      "metadata": {}
    },
    {
      "type": "deployment",
      "timestamp": "2026-09-29T09:25:00Z",
      "service": "checkout",
      "message": "Deployment checkout-v2",
      "metadata": {
        "version": "v2"
      }
    }
  ]
}
```

Response — `202 Accepted`:

JSON

```
{
  "incident_id": "inc_001",
  "accepted_count": 2,
  "rejected_count": 0
}
```

The backend validates and normalizes each evidence item before saving it. We should add deduplication if the telemetry source can resend the same records.

## F. List evidence

`GET /api/v1/incidents/{id}/evidence?limit=50&offset=0&type=log`

Response — `200 OK`:

JSON

```
{
  "items": [
    {
      "id": "ev_001",
      "incident_id": "inc_001",
      "type": "log",
      "timestamp": "2026-09-29T09:32:10Z",
      "service": "checkout",
      "severity": "error",
      "message": "Database connection timeout",
      "trace_id": "trace_abc123",
      "source": "otel",
      "metadata": {}
    }
  ],
  "total": 1,
  "limit": 50,
  "offset": 0
}
```

## G. Start an investigation

`POST /api/v1/incidents/{id}/investigations`

Request:

JSON

```
{
  "time_window": {
    "start": "2026-09-29T09:20:00Z",
    "end": "2026-09-29T09:40:00Z"
  }
}
```

Response — `202 Accepted`:

JSON

```
{
  "job_id": "job_001",
  "incident_id": "inc_001",
  "status": "queued",
  "created_at": "2026-09-29T09:35:00Z"
}
```

The backend queues the investigation and returns immediately. This avoids keeping an HTTP request open while the AI model reasons over the evidence.

## H. Check investigation progress

`GET /api/v1/investigations/{job_id}`

Response — `200 OK`:

JSON

```
{
  "job_id": "job_001",
  "incident_id": "inc_001",
  "status": "running",
  "stage": "analyzing_evidence",
  "progress": 60,
  "created_at": "2026-09-29T09:35:00Z",
  "completed_at": null,
  "error": null
}
```

Allowed job statuses:

* `queued`

* `running`

* `completed`

* `failed`

The `stage` and `progress` are optional convenience fields for the UI. Progress should only be displayed if the backend can provide a meaningful estimate; it should not be fabricated.

## I. Retrieve the report

`GET /api/v1/investigations/{job_id}/report`

Response — `200 OK`:

JSON

```
{
  "id": "report_001",
  "incident_id": "inc_001",
  "status": "completed",
  "summary": "Checkout requests experienced database connection timeouts.",
  "hypotheses": [
    {
      "id": "hyp_001",
      "description": "A recent deployment may have caused connection pool exhaustion.",
      "status": "possible",
      "supporting_evidence": ["ev_001"],
      "contradicting_evidence": [],
      "missing_evidence": ["Database connection pool metrics"],
      "next_step": "Inspect connection pool usage around the deployment."
    }
  ],
  "created_at": "2026-09-29T09:36:00Z"
}
```

If the investigation is still running, return `409 Conflict` with a consistent error body rather than an incomplete report.


# 5. Standard error format

Every endpoint should return errors in the same structure.

JSON

```
{
  "error": {
    "code": "INCIDENT_NOT_FOUND",
    "message": "The requested incident was not found.",
    "details": {}
  }
}
```

|
HTTP status

|

Meaning

|
| --- | --- |
|

`400`

|

Invalid request or malformed data

|
|

`404`

|

Incident, evidence or job not found

|
|

`409`

|

Operation conflicts with current resource state

|
|

`422`

|

Request fields fail validation

|
|

`500`

|

Unexpected backend error

|
|

`503`

|

Required dependency unavailable, such as the model server

|

Do not return stack traces, API keys, prompts containing secrets or internal infrastructure details to the frontend.

# 6. Frontend workflow

1. Dashboard loads

   `GET /api/v1/incidents`

   The frontend displays the incident cards and their status.

2. User opens an incident

   `GET /api/v1/incidents/{id}`

   `GET /api/v1/incidents/{id}/evidence`

   The frontend shows the incident information and timeline.

3. User starts investigation

   `POST /api/v1/incidents/{id}/investigations`

   The backend returns a `job_id`.

4. Frontend checks progress

   `GET /api/v1/investigations/{job_id}`

   Poll approximately every 2–3 seconds while the job is running.

5. Investigation completes

   `GET /api/v1/investigations/{job_id}/report`

   The frontend renders the hypotheses, supporting evidence and next steps.

# 7. Decisions to freeze for the team

Recommended MVP contract

* Frontend: Next.js consumes REST APIs only.

* Backend: FastAPI owns validation, data access, evidence processing and AI orchestration.

* Database: PostgreSQL stores incidents, selected evidence, investigation jobs and reports.

* AI: The backend calls Ollama; the frontend never calls the model directly.

* Investigation: Asynchronous job with status polling.

* Report: Structured JSON with hypotheses linked to evidence IDs.

* Telemetry: Simple REST ingestion for the initial test harness; OpenTelemetry Collector integration can feed the evidence pipeline separately.

* Authentication: Keep out of the first local demo if it is strictly single-user, but do not expose the service publicly without adding authentication and authorization.

One implementation detail worth enforcing: define these objects as Pydantic models in the backend, then use the generated OpenAPI schema as the shared reference for frontend types. That reduces drift between what the backend sends and what the frontend expects.

## 8. Team ownership

|
Member

|

Responsibility

|
| --- | --- |
|

You

|

FastAPI incident/evidence APIs, database models, integration

|
|

Experienced teammate

|

Investigation job, Ollama integration, report schema and agent

|
|

Beginner 1

|

Next.js dashboard, incident details and report UI using mock JSON first

|
|

Beginner 2

|

Test harness, telemetry samples, API testing and reproducible failure scenarios

|

These contracts are a proposed baseline, not yet implemented or tested. Once the team agrees, keep the field names and status values stable; changes should be communicated before either side implements against an outdated version.

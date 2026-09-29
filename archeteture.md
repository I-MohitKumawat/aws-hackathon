# Final Architecture: Self-Hosted AI Software Incident Investigator

A privacy-focused, Docker-based system that collects telemetry, correlates incident evidence and uses a local LLM to investigate possible root causes.

Application / Microservices

OpenTelemetry Astronomy Shop

Logs

Metrics

Traces

OpenTelemetry Collector

Receives, processes and exports telemetry

Investigation Backend · Python

Evidence Processor

Parse, normalize, filter and correlate

AI Agent

Investigate, form hypotheses and request evidence

Queries evidence storage and calls the local models

PostgreSQL + pgvector

Incident data, structured evidence, embeddings and reports

Ollama

Local LLM and embedding model inference

Report Validation

Verify evidence references, format findings and mark uncertainty

Next.js Frontend

Incident dashboard · Timeline · Root-cause hypotheses · Evidence-backed report

Self-hosted within the customer's infrastructure; incident data does not need to leave their environment.

## Technology stack

|
Layer

|

Technology

|

Responsibility

|
| --- | --- | --- |
|

Demo application

|

OpenTelemetry Astronomy Shop

|

Simulates a distributed application

|
|

Containerization

|

Docker Compose

|

Runs the application and supporting services

|
|

Telemetry

|

OpenTelemetry Collector

|

Collects and exports logs, metrics and traces

|
|

Frontend

|

Next.js

|

Dashboard and investigation report

|
|

API

|

Next.js API routes

|

Authentication, incident requests and report delivery

|
|

AI backend

|

Python

|

Evidence processing, retrieval and agent orchestration

|
|

Database

|

PostgreSQL + `pgvector`

|

Stores incident evidence, metadata, embeddings and reports

|
|

LLM runtime

|

Ollama

|

Runs models locally

|
|

LLM

|

Qwen3 (small suitable variant)

|

Hypothesis generation and evidence reasoning

|
|

Embedding model

|

all-minilm (384d)

|

Semantic retrieval of relevant text

|
|

Retrieval

|

SQL + vector search

|

Structured and semantic evidence retrieval

|

## Investigation workflow

1. Failure is introduced in the demo application, and an incident is triggered.

2. Telemetry is collected through the OpenTelemetry Collector.

3. Evidence is processed by Python: normalized, time-filtered and correlated by service, trace ID and other identifiers.

4. Evidence is stored in PostgreSQL. SQL handles exact queries; `pgvector` retrieves semantically relevant text when useful.

5. The AI agent investigates using retrieved evidence and read-only tools to request more information when needed.

6. The report is validated to ensure evidence references exist and unsupported conclusions are not presented as facts.

7. The Next.js dashboard displays the incident timeline, hypotheses, supporting and contradicting evidence, and missing information.

## Deployment and privacy

Docker Compose deployment

Run the Next.js app, Python worker, PostgreSQL and Ollama in containers alongside the OpenTelemetry demo and Collector. Keep the model and database on the customer's own host or private infrastructure.

Core security controls

* Authentication and role-based access to incidents and reports.

* Secrets stored outside source code and container images.

* Read-only evidence retrieval tools for the agent.

* Redaction of credentials and sensitive information.

* Configurable retention and deletion of incident data.

* No automatic external model API calls or telemetry sharing.

## Scope for the first working prototype

Build now

* One OpenTelemetry demo application and one controlled failure.

* Collection of a limited set of real logs and traces.

* Python-based structured retrieval with PostgreSQL.

* A local LLM generating a hypothesis and citing evidence IDs.

* A basic Next.js dashboard showing the result.

Add later

* More observability and CI/CD integrations.

* Semantic retrieval across historical incidents and code changes.

* Dynamic agent tool-calling and multiple hypotheses.

* Multi-user administration, advanced authorization and production hardening.

The central idea: conventional code collects and correlates the evidence, RAG retrieves the relevant context, and the LLM investigates that context to produce an evidence-backed hypothesis. The system assists engineers with root-cause investigation; it does not replace existing CI/CD or monitoring automation.

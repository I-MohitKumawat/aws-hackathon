from datetime import datetime
from backend.app.schemas import (
    IncidentCreate,
    IncidentResponse,
    TelemetryIngestRequest,
    EvidenceResponse,
    InvestigationJobStatusResponse,
    InvestigationReportResponse,
)

def test_incident_schemas():
    create_payload = {
        "title": "Checkout service timeout",
        "service": "checkout",
        "severity": "high",
        "started_at": "2026-09-29T09:30:00Z",
        "description": "Checkout requests are timing out.",
    }
    incident_create = IncidentCreate.model_validate(create_payload)
    assert incident_create.title == "Checkout service timeout"
    assert incident_create.severity == "high"

    resp_payload = {
        "id": "inc_001",
        "title": "Checkout service timeout",
        "service": "checkout",
        "severity": "high",
        "status": "open",
        "started_at": "2026-09-29T09:30:00Z",
        "ended_at": None,
        "created_at": "2026-09-29T09:31:00Z",
    }
    incident_resp = IncidentResponse.model_validate(resp_payload)
    assert incident_resp.id == "inc_001"
    assert incident_resp.status == "open"
    assert incident_resp.ended_at is None

def test_telemetry_schemas():
    telemetry_payload = {
        "incident_id": "inc_001",
        "evidence": [
            {
                "type": "log",
                "timestamp": "2026-09-29T09:32:10Z",
                "service": "checkout",
                "severity": "error",
                "message": "Database connection timeout",
                "trace_id": "trace_abc123",
                "metadata": {},
            },
            {
                "type": "deployment",
                "timestamp": "2026-09-29T09:25:00Z",
                "service": "checkout",
                "message": "Deployment checkout-v2",
                "metadata": {"version": "v2"},
            },
        ],
    }
    req = TelemetryIngestRequest.model_validate(telemetry_payload)
    assert req.incident_id == "inc_001"
    assert len(req.evidence) == 2
    assert req.evidence[0].source == "otel"

def test_investigation_and_report_schemas():
    job_payload = {
        "job_id": "job_001",
        "incident_id": "inc_001",
        "status": "running",
        "stage": "analyzing_evidence",
        "progress": 60,
        "created_at": "2026-09-29T09:35:00Z",
        "completed_at": None,
        "error": None,
    }
    job = InvestigationJobStatusResponse.model_validate(job_payload)
    assert job.job_id == "job_001"
    assert job.progress == 60

    report_payload = {
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
                "next_step": "Inspect connection pool usage around the deployment.",
            }
        ],
        "created_at": "2026-09-29T09:36:00Z",
    }
    report = InvestigationReportResponse.model_validate(report_payload)
    assert report.id == "report_001"
    assert len(report.hypotheses) == 1
    assert report.hypotheses[0].status == "possible"

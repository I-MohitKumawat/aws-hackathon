import pytest
from unittest.mock import AsyncMock
from datetime import datetime, timezone
import uuid
import json

from backend.app.database import SessionLocal
from backend.app.models import Incident, Evidence, InvestigationJob, InvestigationReport
from backend.app.services.investigation_service import execute_investigation
from backend.app.agent import OllamaClient, OllamaConnectionError
from backend.tests.fixtures.controlled_incident import (
    get_controlled_incident_models,
)
from backend.tests.test_agent_ollama import REPRESENTATIVE_MODEL_OUTPUT

@pytest.mark.asyncio
async def test_investigation_lifecycle_success():
    db = SessionLocal()
    try:
        # 1. Seed incident and evidence
        incident, evidence_items = get_controlled_incident_models()
        # Ensure fresh IDs to avoid duplicate collisions across test runs
        unique_suffix = uuid.uuid4().hex[:6]
        incident.id = f"{incident.id}_{unique_suffix}"
        for ev in evidence_items:
            ev.id = f"{ev.id}_{unique_suffix}"
            ev.incident_id = incident.id

        db.add(incident)
        for ev in evidence_items:
            db.add(ev)

        # 2. Create Job
        job_id = f"job_test_{unique_suffix}"
        job = InvestigationJob(
            job_id=job_id,
            incident_id=incident.id,
            status="queued",
            stage="queued",
            progress=0,
            created_at=datetime.now(timezone.utc),
        )
        db.add(job)
        db.commit()

        # 3. Prepare mock response citing the valid seeded evidence IDs
        valid_ev_ids = [ev.id for ev in evidence_items]
        mock_output = json.dumps({
            "summary": "Checkout connection timeout investigation.",
            "hypotheses": [
                {
                    "id": "hyp_01",
                    "description": "Post-deployment connection pool exhaustion.",
                    "status": "possible",
                    "supporting_evidence": valid_ev_ids,
                    "contradicting_evidence": [],
                    "missing_evidence": ["Active lock queries"],
                    "next_step": "Check Postgres locks.",
                }
            ]
        })

        mock_client = AsyncMock(spec=OllamaClient)
        mock_client.generate.return_value = mock_output

        # 4. Execute investigation
        await execute_investigation(job_id=job_id, client=mock_client)

        # 5. Verify DB updates
        db.refresh(job)
        assert job.status == "completed"
        assert job.stage == "report_ready"
        assert job.progress == 100
        assert job.completed_at is not None
        assert job.error is None

        # Verify Report
        report = db.query(InvestigationReport).filter(InvestigationReport.job_id == job_id).first()
        assert report is not None
        assert report.incident_id == incident.id
        assert report.status == "completed"
        assert report.summary == "Checkout connection timeout investigation."
        assert len(report.hypotheses_json) == 1
        assert report.hypotheses_json[0]["supporting_evidence"] == valid_ev_ids

    finally:
        db.close()

@pytest.mark.asyncio
async def test_investigation_lifecycle_ollama_connection_failure():
    db = SessionLocal()
    try:
        incident, evidence_items = get_controlled_incident_models()
        unique_suffix = uuid.uuid4().hex[:6]
        incident.id = f"{incident.id}_{unique_suffix}"
        for ev in evidence_items:
            ev.id = f"{ev.id}_{unique_suffix}"
            ev.incident_id = incident.id

        db.add(incident)
        for ev in evidence_items:
            db.add(ev)

        job_id = f"job_fail_{unique_suffix}"
        job = InvestigationJob(
            job_id=job_id,
            incident_id=incident.id,
            status="queued",
            created_at=datetime.now(timezone.utc),
        )
        db.add(job)
        db.commit()

        mock_client = AsyncMock(spec=OllamaClient)
        mock_client.generate.side_effect = OllamaConnectionError("Could not reach Ollama at http://localhost:11434")

        # Execute investigation
        await execute_investigation(job_id=job_id, client=mock_client)

        db.refresh(job)
        assert job.status == "failed"
        assert "Could not reach Ollama" in job.error
        assert job.completed_at is not None

        # Verify no report was persisted
        report = db.query(InvestigationReport).filter(InvestigationReport.job_id == job_id).first()
        assert report is None

    finally:
        db.close()

@pytest.mark.asyncio
async def test_investigation_lifecycle_fabricated_evidence_failure():
    db = SessionLocal()
    try:
        incident, evidence_items = get_controlled_incident_models()
        unique_suffix = uuid.uuid4().hex[:6]
        incident.id = f"{incident.id}_{unique_suffix}"
        for ev in evidence_items:
            ev.id = f"{ev.id}_{unique_suffix}"
            ev.incident_id = incident.id

        db.add(incident)
        for ev in evidence_items:
            db.add(ev)

        job_id = f"job_fab_{unique_suffix}"
        job = InvestigationJob(
            job_id=job_id,
            incident_id=incident.id,
            status="queued",
            created_at=datetime.now(timezone.utc),
        )
        db.add(job)
        db.commit()

        # Output with fabricated evidence ID
        bad_output = json.dumps({
            "summary": "Suspected issue.",
            "hypotheses": [
                {
                    "id": "hyp_01",
                    "description": "Hallucinated evidence.",
                    "status": "possible",
                    "supporting_evidence": ["ev_nonexistent_9999"],
                    "contradicting_evidence": [],
                    "missing_evidence": [],
                    "next_step": "Investigate.",
                }
            ]
        })

        mock_client = AsyncMock(spec=OllamaClient)
        mock_client.generate.return_value = bad_output

        await execute_investigation(job_id=job_id, client=mock_client)

        db.refresh(job)
        assert job.status == "failed"
        assert "fabricated or unknown evidence ID" in job.error

        report = db.query(InvestigationReport).filter(InvestigationReport.job_id == job_id).first()
        assert report is None

    finally:
        db.close()

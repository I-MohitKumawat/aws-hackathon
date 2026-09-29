import pytest
from unittest.mock import AsyncMock
from datetime import datetime, timezone
import uuid
import json

from sqlalchemy.orm import Session
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

@pytest.mark.asyncio
async def test_investigation_lifecycle_time_window_filtering():
    """Verify that evidence outside the investigation time window is excluded."""
    db = SessionLocal()
    try:
        unique_suffix = uuid.uuid4().hex[:6]
        incident = Incident(
            id=f"inc_window_{unique_suffix}",
            title="Window Test Incident",
            service="checkout",
            severity="high",
            status="open",
            started_at=datetime(2026, 9, 29, 9, 0, 0, tzinfo=timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        db.add(incident)

        # Evidence: 1 outside before, 2 inside, 1 outside after
        ev_before = Evidence(
            id=f"ev_out_before_{unique_suffix}",
            incident_id=incident.id,
            type="log",
            timestamp=datetime(2026, 9, 29, 9, 10, 0, tzinfo=timezone.utc),
            service="checkout",
            message="Early log",
            source="otel",
            metadata_json={},
            created_at=datetime.now(timezone.utc),
        )
        ev_inside1 = Evidence(
            id=f"ev_in_1_{unique_suffix}",
            incident_id=incident.id,
            type="log",
            timestamp=datetime(2026, 9, 29, 9, 25, 0, tzinfo=timezone.utc),
            service="checkout",
            message="Inside window log 1",
            source="otel",
            metadata_json={},
            created_at=datetime.now(timezone.utc),
        )
        ev_inside2 = Evidence(
            id=f"ev_in_2_{unique_suffix}",
            incident_id=incident.id,
            type="metric",
            timestamp=datetime(2026, 9, 29, 9, 30, 0, tzinfo=timezone.utc),
            service="checkout",
            message="Inside window metric 2",
            source="otel",
            metadata_json={},
            created_at=datetime.now(timezone.utc),
        )
        ev_after = Evidence(
            id=f"ev_out_after_{unique_suffix}",
            incident_id=incident.id,
            type="log",
            timestamp=datetime(2026, 9, 29, 9, 50, 0, tzinfo=timezone.utc),
            service="checkout",
            message="Late log",
            source="otel",
            metadata_json={},
            created_at=datetime.now(timezone.utc),
        )
        for ev in [ev_before, ev_inside1, ev_inside2, ev_after]:
            db.add(ev)

        # Job with window 09:20 to 09:35
        job_id = f"job_win_{unique_suffix}"
        job = InvestigationJob(
            job_id=job_id,
            incident_id=incident.id,
            status="queued",
            time_window_start=datetime(2026, 9, 29, 9, 20, 0, tzinfo=timezone.utc),
            time_window_end=datetime(2026, 9, 29, 9, 35, 0, tzinfo=timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        db.add(job)
        db.commit()

        # Capture prompt passed to model
        captured_prompts = []
        async def mock_generate(prompt, system=None, options=None, **kwargs):
            captured_prompts.append(prompt)
            return json.dumps({
                "summary": "Window test summary.",
                "hypotheses": [
                    {
                        "id": "hyp_01",
                        "description": "Issue within window.",
                        "status": "possible",
                        "supporting_evidence": [ev_inside1.id, ev_inside2.id],
                        "contradicting_evidence": [],
                        "missing_evidence": [],
                        "next_step": "Investigate.",
                    }
                ]
            })

        mock_client = AsyncMock(spec=OllamaClient)
        mock_client.generate.side_effect = mock_generate

        await execute_investigation(job_id=job_id, client=mock_client)

        db.refresh(job)
        assert job.status == "completed"

        # Verify prompt contained ONLY the 2 inside-window evidence items
        assert len(captured_prompts) == 1
        prompt = captured_prompts[0]
        assert ev_inside1.id in prompt
        assert ev_inside2.id in prompt
        assert ev_before.id not in prompt
        assert ev_after.id not in prompt

    finally:
        db.close()

@pytest.mark.asyncio
async def test_investigation_lifecycle_empty_evidence_in_window():
    """Verify that an investigation with zero evidence in window produces a clean inconclusive report."""
    db = SessionLocal()
    try:
        unique_suffix = uuid.uuid4().hex[:6]
        incident = Incident(
            id=f"inc_empty_{unique_suffix}",
            title="Empty Window Test Incident",
            service="checkout",
            severity="medium",
            status="open",
            started_at=datetime(2026, 9, 29, 9, 0, 0, tzinfo=timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        db.add(incident)

        job_id = f"job_empty_{unique_suffix}"
        job = InvestigationJob(
            job_id=job_id,
            incident_id=incident.id,
            status="queued",
            time_window_start=datetime(2026, 9, 29, 8, 0, 0, tzinfo=timezone.utc),
            time_window_end=datetime(2026, 9, 29, 8, 15, 0, tzinfo=timezone.utc),
            created_at=datetime.now(timezone.utc),
        )
        db.add(job)
        db.commit()

        mock_client = AsyncMock(spec=OllamaClient)
        await execute_investigation(job_id=job_id, client=mock_client)

        # Model should not have been called because no evidence existed in scope
        mock_client.generate.assert_not_called()

        db.refresh(job)
        assert job.status == "completed"
        assert job.stage == "report_ready"

        report = db.query(InvestigationReport).filter(InvestigationReport.job_id == job_id).first()
        assert report is not None
        assert "No telemetry evidence" in report.summary
        assert len(report.hypotheses_json) == 1
        assert report.hypotheses_json[0]["status"] == "inconclusive"
        assert report.hypotheses_json[0]["supporting_evidence"] == []

    finally:
        db.close()

@pytest.mark.asyncio
async def test_investigation_lifecycle_report_persistence_failure():
    """Verify that a database persistence error transitions job to 'failed' and never leaves it 'running'."""
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

        job_id = f"job_persist_fail_{unique_suffix}"
        job = InvestigationJob(
            job_id=job_id,
            incident_id=incident.id,
            status="queued",
            created_at=datetime.now(timezone.utc),
        )
        db.add(job)
        db.commit()

        mock_output = json.dumps({
            "summary": "Valid summary.",
            "hypotheses": [
                {
                    "id": "hyp_01",
                    "description": "Valid desc.",
                    "status": "possible",
                    "supporting_evidence": [evidence_items[0].id],
                    "contradicting_evidence": [],
                    "missing_evidence": [],
                    "next_step": "Step.",
                }
            ]
        })
        mock_client = AsyncMock(spec=OllamaClient)
        mock_client.generate.return_value = mock_output

        # Patch db.add to simulate a database failure during report insertion
        from unittest.mock import patch
        with patch.object(Session, "add", side_effect=RuntimeError("Simulated DB Disk Failure")):
            await execute_investigation(job_id=job_id, client=mock_client)

        db.refresh(job)
        assert job.status == "failed"
        assert "Simulated DB Disk Failure" in job.error
        assert job.completed_at is not None

    finally:
        db.close()

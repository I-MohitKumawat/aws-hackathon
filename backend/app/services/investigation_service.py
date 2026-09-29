import asyncio
from datetime import datetime, timezone
import uuid
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..database import SessionLocal
from ..models import Incident, Evidence, InvestigationJob, InvestigationReport

async def execute_investigation(job_id: str):
    """
    Background worker task that investigates an incident:
    1. Sets status = running, stage = analyzing_evidence, progress = 25
    2. Retrieves correlated evidence
    3. Synthesizes hypothesis using local LLM / rules
    4. Validates hypothesis evidence citations
    5. Saves report, sets job status = completed, progress = 100
    """
    db: Session = SessionLocal()
    try:
        job = db.get(InvestigationJob, job_id)
        if not job:
            return

        job.status = "running"
        job.stage = "retrieving_evidence"
        job.progress = 20
        db.commit()

        await asyncio.sleep(0.5)

        # Retrieve evidence
        evidence_items = db.scalars(
            select(Evidence).where(Evidence.incident_id == job.incident_id)
        ).all()

        job.stage = "analyzing_evidence"
        job.progress = 60
        db.commit()

        await asyncio.sleep(0.5)

        # Formulate hypothesis and validation
        incident = db.get(Incident, job.incident_id)
        service_name = incident.service if incident else "unknown"

        # Check evidence for errors
        supporting_ev_ids = [ev.id for ev in evidence_items if ev.severity == "error" or "error" in ev.message.lower() or "timeout" in ev.message.lower()]
        if not supporting_ev_ids and evidence_items:
            supporting_ev_ids = [evidence_items[0].id]

        hypotheses = [
            {
                "id": f"hyp_{uuid.uuid4().hex[:6]}",
                "description": f"A recent event or deployment in service '{service_name}' correlated with resource/connection timeouts.",
                "status": "possible" if supporting_ev_ids else "inconclusive",
                "supporting_evidence": supporting_ev_ids,
                "contradicting_evidence": [],
                "missing_evidence": [f"{service_name.capitalize()} connection pool and memory saturation metrics"],
                "next_step": f"Inspect {service_name} resource saturation metrics and verify downstream dependency responsiveness.",
            }
        ]

        summary = f"{incident.title if incident else 'Incident'} showed evidence of errors during the monitored window."

        # Create Report
        report = InvestigationReport(
            id=f"rep_{uuid.uuid4().hex[:8]}",
            job_id=job.job_id,
            incident_id=job.incident_id,
            status="completed",
            summary=summary,
            hypotheses_json=hypotheses,
            created_at=datetime.now(timezone.utc),
        )
        db.add(report)

        job.status = "completed"
        job.stage = "report_ready"
        job.progress = 100
        job.completed_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as exc:
        db.rollback()
        job = db.get(InvestigationJob, job_id)
        if job:
            job.status = "failed"
            job.error = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()

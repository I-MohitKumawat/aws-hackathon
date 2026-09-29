import asyncio
from datetime import datetime, timezone
import uuid
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..database import SessionLocal
from ..models import Incident, Evidence, InvestigationJob, InvestigationReport
from ..agent import (
    OllamaClient,
    OllamaClientError,
    SYSTEM_PROMPT,
    build_investigation_prompt,
    validate_model_investigation_output,
    RawAIInvestigationOutput,
    ReportValidationError,
)

async def investigate_incident(
    incident: Incident,
    evidence_items: List[Evidence],
    client: Optional[OllamaClient] = None,
) -> RawAIInvestigationOutput:
    """
    Performs AI-grounded investigation on an incident and its evidence:
    1. Formulates the prompt.
    2. Sends inference request to Ollama.
    3. Validates and parses the model's output against the schema and evidence references.
    """
    ollama_client = client or OllamaClient()
    prompt = build_investigation_prompt(incident, evidence_items)
    valid_evidence_ids = {ev.id for ev in evidence_items}

    raw_response = await ollama_client.generate(prompt=prompt, system=SYSTEM_PROMPT)
    validated_output = validate_model_investigation_output(
        raw_output=raw_response,
        valid_evidence_ids=valid_evidence_ids,
    )
    return validated_output

async def execute_investigation(job_id: str, client: Optional[OllamaClient] = None):
    """
    Background worker task that drives the investigation job lifecycle:
    1. Sets status = running, stage = retrieving_evidence, progress = 20
    2. Retrieves incident & correlated evidence from DB
    3. Sets stage = analyzing_evidence, progress = 50
    4. Calls investigate_incident (Ollama + Validator)
    5. Persists report, sets job status = completed, stage = report_ready, progress = 100
    6. On error, records failure details and sets status = failed
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

        # Retrieve incident and evidence
        incident = db.get(Incident, job.incident_id)
        if not incident:
            job.status = "failed"
            job.error = f"Incident '{job.incident_id}' not found."
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        evidence_items = db.scalars(
            select(Evidence).where(Evidence.incident_id == job.incident_id)
        ).all()

        job.stage = "analyzing_evidence"
        job.progress = 50
        db.commit()

        # Call AI investigation
        validated_output = await investigate_incident(
            incident=incident,
            evidence_items=evidence_items,
            client=client,
        )

        # Create and persist Report
        report = InvestigationReport(
            id=f"rep_{uuid.uuid4().hex[:8]}",
            job_id=job.job_id,
            incident_id=job.incident_id,
            status="completed",
            summary=validated_output.summary,
            hypotheses_json=[h.model_dump() for h in validated_output.hypotheses],
            created_at=datetime.now(timezone.utc),
        )
        db.add(report)

        job.status = "completed"
        job.stage = "report_ready"
        job.progress = 100
        job.completed_at = datetime.now(timezone.utc)
        db.commit()

    except (OllamaClientError, ReportValidationError, Exception) as exc:
        db.rollback()
        job = db.get(InvestigationJob, job_id)
        if job:
            job.status = "failed"
            job.error = str(exc)
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
    finally:
        db.close()

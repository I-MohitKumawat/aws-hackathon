import asyncio
from datetime import datetime, timezone
import uuid
from typing import Optional, List
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..database import SessionLocal
from ..config import settings
from ..models import Incident, Evidence, InvestigationJob, InvestigationReport
from ..schemas.report import Hypothesis
from ..agent import (
    OllamaClient,
    OllamaClientError,
    EmbeddingClient,
    SYSTEM_PROMPT,
    INVESTIGATION_REPORT_JSON_SCHEMA,
    build_investigation_prompt,
    validate_model_investigation_output,
    RawAIInvestigationOutput,
    ReportValidationError,
)
from .retrieval_service import retrieve_evidence_for_investigation

async def investigate_incident(
    incident: Incident,
    evidence_items: List[Evidence],
    client: Optional[OllamaClient] = None,
) -> RawAIInvestigationOutput:
    """
    Executes AI-grounded incident investigation over correlated evidence:
    1. If evidence is empty, produces a factual inconclusive report noting missing telemetry.
    2. Otherwise, constructs the focused investigation prompt with strictly valid evidence IDs.
    3. Requests structured inference from Ollama using the formal report JSON Schema.
    4. Validates schema and verifies that all cited evidence IDs exist.
    """
    if not evidence_items:
        return RawAIInvestigationOutput(
            summary=f"No telemetry evidence was recorded for incident '{incident.title}' within the investigated scope.",
            hypotheses=[
                Hypothesis(
                    id="hyp_no_evidence",
                    description="Insufficient telemetry evidence available to establish root-cause hypotheses.",
                    status="inconclusive",
                    supporting_evidence=[],
                    contradicting_evidence=[],
                    missing_evidence=[
                        f"Application logs, error metrics, and distributed traces for service '{incident.service}'",
                    ],
                    next_step="Verify telemetry ingestion collectors and widen the investigation time window.",
                )
            ],
        )

    ollama_client = client or OllamaClient()
    prompt = build_investigation_prompt(incident, evidence_items)
    valid_evidence_ids = {ev.id for ev in evidence_items}

    raw_response = await ollama_client.generate(
        prompt=prompt,
        system=SYSTEM_PROMPT,
        response_format=INVESTIGATION_REPORT_JSON_SCHEMA,
    )
    validated_output = validate_model_investigation_output(
        raw_output=raw_response,
        valid_evidence_ids=valid_evidence_ids,
    )
    return validated_output

async def execute_investigation(
    job_id: str,
    client: Optional[OllamaClient] = None,
    embedding_client: Optional[EmbeddingClient] = None,
):
    """
    Background worker orchestrating the investigation job lifecycle:
    1. Sets status = running, stage = retrieving_evidence, progress = 20
    2. Retrieves evidence using hybrid vector similarity and time-window filtering
    3. Sets stage = analyzing_evidence, progress = 50
    4. Calls investigate_incident (Ollama + Validator)
    5. Persists report and sets status = completed atomically
    6. On error, records failure details and sets status = failed with fresh session fallback
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

        # Retrieve incident
        incident = db.get(Incident, job.incident_id)
        if not incident:
            job.status = "failed"
            job.error = f"Incident '{job.incident_id}' not found."
            job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return

        # Retrieve evidence applying time-window filters and semantic/heuristic ranking
        evidence_items = await retrieve_evidence_for_investigation(
            db=db,
            incident=incident,
            job=job,
            top_k=settings.RETRIEVAL_TOP_K,
            embedding_client=embedding_client,
        )

        job.stage = "analyzing_evidence"
        job.progress = 50
        db.commit()

        # Call AI investigation
        validated_output = await investigate_incident(
            incident=incident,
            evidence_items=evidence_items,
            client=client,
        )

        # Create and persist Report atomically with job completion
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
        job.error = None
        db.commit()

    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass

        # Use an isolated session to ensure job failure is reliably recorded
        try:
            fail_db = SessionLocal()
            try:
                fail_job = fail_db.get(InvestigationJob, job_id)
                if fail_job:
                    fail_job.status = "failed"
                    fail_job.error = str(exc)
                    fail_job.completed_at = datetime.now(timezone.utc)
                    fail_db.commit()
            finally:
                fail_db.close()
        except Exception as inner_exc:
            print(f"CRITICAL: Failed to update investigation job {job_id} to failed state: {inner_exc}")
    finally:
        try:
            db.close()
        except Exception:
            pass

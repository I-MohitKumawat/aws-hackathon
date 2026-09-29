import asyncio
import logging
from datetime import datetime, timezone
import uuid
from typing import Optional, List, Dict, Any
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

logger = logging.getLogger(__name__)

# Bounded semaphore to limit parallel AI investigations and protect Ollama / system resources
_investigation_semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_INVESTIGATIONS)

def get_investigation_semaphore() -> asyncio.Semaphore:
    """Returns the global investigation semaphore for concurrency control."""
    return _investigation_semaphore

def recover_orphaned_jobs(db: Session) -> Dict[str, int]:
    """
    Sweeps for orphaned jobs left in 'queued' or 'running' status after a backend restart.
    - If retry_count < max_retries: requeues the job.
    - If retry_count >= max_retries: marks the job as failed with a clear failure explanation.
    """
    orphaned_jobs = db.execute(
        select(InvestigationJob).where(InvestigationJob.status.in_(["queued", "running"]))
    ).scalars().all()

    requeued = 0
    aborted = 0
    now = datetime.now(timezone.utc)

    for job in orphaned_jobs:
        current_retries = (job.retry_count or 0) + 1
        job.retry_count = current_retries
        job.updated_at = now

        if current_retries <= job.max_retries:
            job.status = "queued"
            job.stage = "requeued_after_restart"
            job.progress = 0
            job.error = f"Recovered after server restart (attempt {current_retries}/{job.max_retries})"
            requeued += 1
            logger.warning("Re-queued orphaned investigation job %s (attempt %d/%d)", job.job_id, current_retries, job.max_retries)
        else:
            job.status = "failed"
            job.stage = "aborted_retry_limit"
            job.error = f"Job aborted: maximum retry limit ({job.max_retries}) reached after server restart."
            job.completed_at = now
            aborted += 1
            logger.error("Aborted orphaned investigation job %s after reaching retry limit (%d)", job.job_id, job.max_retries)

    if orphaned_jobs:
        db.commit()

    return {
        "requeued": requeued,
        "aborted": aborted,
        "total_orphaned": len(orphaned_jobs),
    }

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
    Background worker orchestrating the investigation job lifecycle with:
    - Global concurrency limit via semaphore
    - Timeout deadlines on inference
    - Configurable retries on transient errors
    - Atomic status and report persistence
    """
    async with _investigation_semaphore:
        db: Session = SessionLocal()
        try:
            job = db.get(InvestigationJob, job_id)
            if not job:
                return

            incident = db.get(Incident, job.incident_id)
            if not incident:
                job.status = "failed"
                job.error = f"Incident '{job.incident_id}' not found."
                job.completed_at = datetime.now(timezone.utc)
                job.updated_at = datetime.now(timezone.utc)
                db.commit()
                return

            # Main execution with retry loop
            last_error: Optional[Exception] = None
            start_attempt = job.retry_count or 0

            for attempt in range(start_attempt, (job.max_retries or 2) + 1):
                try:
                    job.status = "running"
                    job.stage = "retrieving_evidence"
                    job.progress = 20
                    job.updated_at = datetime.now(timezone.utc)
                    db.commit()

                    # Retrieve evidence applying time-window filters and semantic ranking
                    evidence_items = await retrieve_evidence_for_investigation(
                        db=db,
                        incident=incident,
                        job=job,
                        top_k=settings.RETRIEVAL_TOP_K,
                        embedding_client=embedding_client,
                    )

                    job.stage = "analyzing_evidence"
                    job.progress = 50
                    job.updated_at = datetime.now(timezone.utc)
                    db.commit()

                    # Execute inference with timeout deadline
                    validated_output = await asyncio.wait_for(
                        investigate_incident(
                            incident=incident,
                            evidence_items=evidence_items,
                            client=client,
                        ),
                        timeout=settings.INVESTIGATION_TIMEOUT_SECONDS,
                    )

                    # Persist Report and complete job atomically
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
                    job.updated_at = datetime.now(timezone.utc)
                    job.error = None
                    db.commit()
                    return

                except Exception as exc:
                    last_error = exc
                    current_attempt = attempt + 1
                    job.retry_count = current_attempt
                    job.updated_at = datetime.now(timezone.utc)

                    if current_attempt <= (job.max_retries or 2):
                        job.status = "queued"
                        job.stage = "retrying"
                        job.error = f"Transient failure during attempt {current_attempt}: {exc}. Retrying..."
                        db.commit()
                        logger.warning("Investigation job %s failed attempt %d: %s. Retrying...", job_id, current_attempt, exc)
                        await asyncio.sleep(1.0)
                    else:
                        raise exc

        except Exception as exc:
            try:
                db.rollback()
            except Exception:
                pass

            # Record failure in isolated session
            try:
                fail_db = SessionLocal()
                try:
                    fail_job = fail_db.get(InvestigationJob, job_id)
                    if fail_job:
                        fail_job.status = "failed"
                        fail_job.stage = "failed"
                        fail_job.error = f"Investigation failed: {str(exc)}"
                        fail_job.completed_at = datetime.now(timezone.utc)
                        fail_job.updated_at = datetime.now(timezone.utc)
                        fail_db.commit()
                finally:
                    fail_db.close()
            except Exception as inner_exc:
                logger.critical("Failed to update investigation job %s to failed state: %s", job_id, inner_exc)
        finally:
            try:
                db.close()
            except Exception:
                pass

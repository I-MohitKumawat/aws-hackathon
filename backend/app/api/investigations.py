from datetime import datetime, timezone
import uuid
from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..database import get_db
from ..models import Incident, InvestigationJob, InvestigationReport
from ..schemas import (
    InvestigationStartRequest,
    InvestigationJobCreateResponse,
    InvestigationJobStatusResponse,
    InvestigationReportResponse,
    Hypothesis,
)
from ..core.exceptions import AppException
from ..services.investigation_service import execute_investigation

incident_investigations_router = APIRouter(prefix="/incidents", tags=["Investigations"])
investigations_router = APIRouter(prefix="/investigations", tags=["Investigations"])

@incident_investigations_router.post(
    "/{id}/investigations",
    response_model=InvestigationJobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def start_investigation(
    id: str,
    payload: InvestigationStartRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    incident = db.get(Incident, id)
    if not incident:
        raise AppException(
            status_code=404,
            code="INCIDENT_NOT_FOUND",
            message="The requested incident was not found.",
            details={"incident_id": id},
        )

    # Update incident status to 'investigating'
    incident.status = "investigating"

    job = InvestigationJob(
        job_id=f"job_{uuid.uuid4().hex[:8]}",
        incident_id=id,
        status="queued",
        stage="queued",
        progress=0,
        time_window_start=payload.time_window.start if payload.time_window else None,
        time_window_end=payload.time_window.end if payload.time_window else None,
        created_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Queue background task
    background_tasks.add_task(execute_investigation, job.job_id)

    return InvestigationJobCreateResponse(
        job_id=job.job_id,
        incident_id=job.incident_id,
        status=job.status,
        created_at=job.created_at,
    )

@investigations_router.get("/{job_id}", response_model=InvestigationJobStatusResponse)
def get_investigation_status(job_id: str, db: Session = Depends(get_db)):
    job = db.get(InvestigationJob, job_id)
    if not job:
        raise AppException(
            status_code=404,
            code="JOB_NOT_FOUND",
            message="The requested investigation job was not found.",
            details={"job_id": job_id},
        )
    return job

@investigations_router.get("/{job_id}/report", response_model=InvestigationReportResponse)
def get_investigation_report(job_id: str, db: Session = Depends(get_db)):
    job = db.get(InvestigationJob, job_id)
    if not job:
        raise AppException(
            status_code=404,
            code="JOB_NOT_FOUND",
            message="The requested investigation job was not found.",
            details={"job_id": job_id},
        )

    if job.status in ["queued", "running"]:
        raise AppException(
            status_code=409,
            code="INVESTIGATION_IN_PROGRESS",
            message="Investigation is still running. Please poll the job status endpoint.",
            details={"job_id": job_id, "status": job.status},
        )

    if job.status == "failed":
        raise AppException(
            status_code=500,
            code="INVESTIGATION_FAILED",
            message=f"Investigation failed: {job.error or 'Unknown reason'}",
            details={"job_id": job_id, "error": job.error},
        )

    report = db.scalar(
        select(InvestigationReport).where(InvestigationReport.job_id == job_id)
    )
    if not report:
        raise AppException(
            status_code=404,
            code="REPORT_NOT_FOUND",
            message="Report for this investigation job was not found.",
            details={"job_id": job_id},
        )

    hypotheses = [Hypothesis(**h) for h in (report.hypotheses_json or [])]

    return InvestigationReportResponse(
        id=report.id,
        incident_id=report.incident_id,
        status=report.status,
        summary=report.summary,
        hypotheses=hypotheses,
        created_at=report.created_at,
    )

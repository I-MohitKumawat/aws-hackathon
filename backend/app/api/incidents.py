from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from ..database import get_db
from ..models import Incident, Evidence
from ..schemas import (
    IncidentCreate,
    IncidentResponse,
    IncidentListResponse,
    IncidentUpdate,
    TelemetryAssociationRequest,
    TelemetryAssociationResponse,
)
from ..core.exceptions import AppException

router = APIRouter(prefix="/incidents", tags=["Incidents"])

@router.post("", response_model=IncidentResponse, status_code=status.HTTP_201_CREATED)
def create_incident(payload: IncidentCreate, db: Session = Depends(get_db)):
    incident = Incident(
        title=payload.title,
        service=payload.service,
        severity=payload.severity,
        status="open",
        description=payload.description,
        started_at=payload.started_at,
        created_at=datetime.now(timezone.utc),
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    return incident

@router.get("", response_model=IncidentListResponse)
def list_incidents(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    query = select(Incident)
    count_query = select(func.count(Incident.id))

    if status:
        query = query.where(Incident.status == status)
        count_query = count_query.where(Incident.status == status)

    total = db.scalar(count_query) or 0
    query = query.order_by(Incident.created_at.desc()).offset(offset).limit(limit)
    items = db.scalars(query).all()

    return IncidentListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )

@router.get("/{id}", response_model=IncidentResponse)
def get_incident(id: str, db: Session = Depends(get_db)):
    incident = db.get(Incident, id)
    if not incident:
        raise AppException(
            status_code=404,
            code="INCIDENT_NOT_FOUND",
            message="The requested incident was not found.",
            details={"incident_id": id},
        )
    return incident

@router.patch("/{id}")
def update_incident(id: str, payload: IncidentUpdate, db: Session = Depends(get_db)):
    incident = db.get(Incident, id)
    if not incident:
        raise AppException(
            status_code=404,
            code="INCIDENT_NOT_FOUND",
            message="The requested incident was not found.",
            details={"incident_id": id},
        )

    if payload.status is not None:
        incident.status = payload.status
    if payload.ended_at is not None:
        incident.ended_at = payload.ended_at
    if payload.title is not None:
        incident.title = payload.title
    if payload.description is not None:
        incident.description = payload.description

    db.commit()
    db.refresh(incident)

    return {
        "id": incident.id,
        "status": incident.status,
        "ended_at": incident.ended_at,
    }

@router.post("/{id}/associate-telemetry", response_model=TelemetryAssociationResponse)
def associate_telemetry_to_incident(
    id: str,
    payload: Optional[TelemetryAssociationRequest] = None,
    db: Session = Depends(get_db),
):
    """
    Explicitly associates unassigned telemetry evidence with the specified incident
    based on service matching and optional time window bounds.
    """
    incident = db.get(Incident, id)
    if not incident:
        raise AppException(
            status_code=404,
            code="INCIDENT_NOT_FOUND",
            message="The requested incident was not found.",
            details={"incident_id": id},
        )

    target_service = payload.service if (payload and payload.service) else incident.service
    window_start = payload.time_window_start if (payload and payload.time_window_start) else None
    window_end = payload.time_window_end if (payload and payload.time_window_end) else None

    # Query unlinked evidence items (where incident_id is NULL)
    query = select(Evidence).where(
        Evidence.incident_id.is_(None),
        Evidence.service == target_service,
    )
    if window_start:
        query = query.where(Evidence.timestamp >= window_start)
    if window_end:
        query = query.where(Evidence.timestamp <= window_end)

    unlinked_items = list(db.scalars(query).all())
    for item in unlinked_items:
        item.incident_id = incident.id

    db.commit()

    return TelemetryAssociationResponse(
        incident_id=incident.id,
        service=target_service,
        associated_count=len(unlinked_items),
        time_window_start=window_start,
        time_window_end=window_end,
    )


from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from ..database import get_db
from ..models import Incident
from ..schemas import (
    IncidentCreate,
    IncidentResponse,
    IncidentListResponse,
    IncidentUpdate,
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

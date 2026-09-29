from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from ..database import get_db
from ..models import Incident, Evidence
from ..schemas import EvidenceListResponse, EvidenceResponse
from ..core.exceptions import AppException

router = APIRouter(prefix="/incidents", tags=["Evidence"])

@router.get("/{id}/evidence", response_model=EvidenceListResponse)
def list_incident_evidence(
    id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    type: Optional[str] = Query(default=None),
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

    query = select(Evidence).where(Evidence.incident_id == id)
    count_query = select(func.count(Evidence.id)).where(Evidence.incident_id == id)

    if type:
        query = query.where(Evidence.type == type)
        count_query = count_query.where(Evidence.type == type)

    total = db.scalar(count_query) or 0
    query = query.order_by(Evidence.timestamp.asc()).offset(offset).limit(limit)
    items = db.scalars(query).all()

    # Map models to response schemas
    response_items = [
        EvidenceResponse(
            id=ev.id,
            incident_id=ev.incident_id,
            type=ev.type,
            timestamp=ev.timestamp,
            service=ev.service,
            severity=ev.severity,
            message=ev.message,
            trace_id=ev.trace_id,
            source=ev.source,
            metadata=ev.metadata_json or {},
        )
        for ev in items
    ]

    return EvidenceListResponse(
        items=response_items,
        total=total,
        limit=limit,
        offset=offset,
    )

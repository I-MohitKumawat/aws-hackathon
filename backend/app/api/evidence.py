from typing import Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import select, func

from ..database import get_db
from ..models import Incident, Evidence
from ..schemas import EvidenceListResponse, EvidenceResponse
from ..core.exceptions import AppException
from ..core.auth import Role, require_roles

router = APIRouter(prefix="/incidents", tags=["Evidence"])

@router.get("/{id}/evidence", response_model=EvidenceListResponse)
def list_incident_evidence(
    id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    type: Optional[str] = Query(default=None),
    trace_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
    _role: str = Depends(require_roles([Role.VIEWER.value, Role.INVESTIGATOR.value, Role.ADMIN.value])),
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

    if trace_id:
        query = query.where(Evidence.trace_id == trace_id)
        count_query = count_query.where(Evidence.trace_id == trace_id)

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

traces_router = APIRouter(prefix="/traces", tags=["Traces"])

@traces_router.get("/{trace_id}")
def get_trace_spans(
    trace_id: str,
    db: Session = Depends(get_db),
    _role: str = Depends(require_roles([Role.VIEWER.value, Role.INVESTIGATOR.value, Role.ADMIN.value])),
):
    """
    Retrieves all correlated spans for a distributed trace across services.
    Enables cross-service root-cause and latency inspection.
    """
    query = select(Evidence).where(
        Evidence.trace_id == trace_id,
        Evidence.type == "trace",
    ).order_by(Evidence.timestamp.asc())

    spans = db.scalars(query).all()
    if not spans:
        raise AppException(
            status_code=404,
            code="TRACE_NOT_FOUND",
            message=f"No spans found for trace ID '{trace_id}'.",
            details={"trace_id": trace_id},
        )

    unique_services = list(dict.fromkeys(s.service for s in spans))
    has_errors = any(s.severity == "error" for s in spans)

    span_items = []
    for s in spans:
        meta = s.metadata_json or {}
        span_items.append({
            "id": s.id,
            "span_id": meta.get("span_id"),
            "parent_span_id": meta.get("parent_span_id"),
            "span_name": meta.get("span_name"),
            "service": s.service,
            "timestamp": s.timestamp,
            "severity": s.severity,
            "status_code": meta.get("status_code"),
            "status_message": meta.get("status_message"),
            "message": s.message,
            "attributes": meta.get("attributes", {}),
            "events": meta.get("events", []),
        })

    return {
        "trace_id": trace_id,
        "spans_count": len(spans),
        "services": unique_services,
        "has_errors": has_errors,
        "spans": span_items,
    }

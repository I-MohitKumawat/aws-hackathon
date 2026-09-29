import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Incident, Evidence
from ..schemas import TelemetryIngestRequest, TelemetryIngestResponse
from ..core.exceptions import AppException

router = APIRouter(prefix="/telemetry", tags=["Telemetry"])

@router.post("", response_model=TelemetryIngestResponse, status_code=status.HTTP_202_ACCEPTED)
def submit_telemetry(payload: TelemetryIngestRequest, db: Session = Depends(get_db)):
    incident = db.get(Incident, payload.incident_id)
    if not incident:
        raise AppException(
            status_code=404,
            code="INCIDENT_NOT_FOUND",
            message="The specified incident for telemetry does not exist.",
            details={"incident_id": payload.incident_id},
        )

    accepted = 0
    rejected = 0

    for item in payload.evidence:
        try:
            ev = Evidence(
                id=f"ev_{uuid.uuid4().hex[:8]}",
                incident_id=payload.incident_id,
                type=item.type,
                timestamp=item.timestamp,
                service=item.service,
                severity=item.severity,
                message=item.message,
                trace_id=item.trace_id,
                source=item.source or "otel",
                metadata_json=item.metadata or {},
            )
            db.add(ev)
            accepted += 1
        except Exception:
            rejected += 1

    db.commit()

    return TelemetryIngestResponse(
        incident_id=payload.incident_id,
        accepted_count=accepted,
        rejected_count=rejected,
    )

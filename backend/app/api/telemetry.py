import logging
import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Incident, Evidence
from ..schemas import TelemetryIngestRequest, TelemetryIngestResponse
from ..core.exceptions import AppException
from ..agent import EmbeddingClient, format_evidence_for_embedding

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telemetry", tags=["Telemetry"])

@router.post("", response_model=TelemetryIngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_telemetry(payload: TelemetryIngestRequest, db: Session = Depends(get_db)):
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
    new_evidence: list[Evidence] = []

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
            new_evidence.append(ev)
            accepted += 1
        except Exception:
            rejected += 1

    # Attempt embedding generation for new evidence items; gracefully skip if unavailable
    if new_evidence:
        try:
            client = EmbeddingClient(timeout_seconds=5.0)
            texts = [format_evidence_for_embedding(ev) for ev in new_evidence]
            embeddings = await client.generate_embeddings_batch(texts)
            for ev, emb in zip(new_evidence, embeddings):
                ev.embedding = emb
        except Exception as exc:
            logger.debug("Skipping inline embedding during telemetry ingestion: %s", exc)

        for ev in new_evidence:
            db.add(ev)

    db.commit()

    return TelemetryIngestResponse(
        incident_id=payload.incident_id,
        accepted_count=accepted,
        rejected_count=rejected,
    )

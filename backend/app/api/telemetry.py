from datetime import datetime, timezone, timedelta
import logging
import uuid
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..models import Incident, Evidence
from ..schemas import TelemetryIngestRequest, TelemetryIngestResponse
from ..core.exceptions import AppException
from ..core.auth import Role, require_roles
from ..agent import EmbeddingClient, format_evidence_for_embedding

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/telemetry", tags=["Telemetry"])

@router.post("", response_model=TelemetryIngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def submit_telemetry(
    payload: TelemetryIngestRequest,
    db: Session = Depends(get_db),
    _role: str = Depends(require_roles([Role.TELEMETRY_COLLECTOR.value, Role.ADMIN.value])),
):
    # Enforce batch size limit to avoid unbounded ingestion payloads
    batch_size = len(payload.evidence)
    if batch_size > settings.MAX_TELEMETRY_BATCH_SIZE:
        raise AppException(
            status_code=422,
            code="BATCH_SIZE_EXCEEDED",
            message=f"Telemetry batch size ({batch_size}) exceeds maximum limit of {settings.MAX_TELEMETRY_BATCH_SIZE}.",
            details={"batch_size": batch_size, "max_limit": settings.MAX_TELEMETRY_BATCH_SIZE},
        )

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
    max_future_time = datetime.now(timezone.utc) + timedelta(hours=24)

    for item in payload.evidence:
        try:
            # Timestamp sanity check: reject future-dated telemetry beyond 24h
            if item.timestamp and item.timestamp.tzinfo is None:
                item_ts = item.timestamp.replace(tzinfo=timezone.utc)
            else:
                item_ts = item.timestamp

            if item_ts and item_ts > max_future_time:
                logger.warning("Rejecting telemetry with future timestamp: %s > %s", item_ts, max_future_time)
                rejected += 1
                continue

            ev = Evidence(
                id=f"ev_{uuid.uuid4().hex[:8]}",
                incident_id=payload.incident_id,
                type=item.type,
                timestamp=item_ts or datetime.now(timezone.utc),
                service=item.service,
                severity=item.severity,
                message=item.message,
                trace_id=item.trace_id,
                source=item.source or "otel",
                metadata_json=item.metadata or {},
            )
            new_evidence.append(ev)
            accepted += 1
        except Exception as exc:
            logger.warning("Failed to parse evidence item: %s", exc)
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

        try:
            for ev in new_evidence:
                db.add(ev)
            db.commit()
        except Exception as db_exc:
            logger.error("Database commit failed during telemetry submission: %s", db_exc)
            try:
                db.rollback()
            except Exception:
                pass
            rejected += accepted
            accepted = 0

    return TelemetryIngestResponse(
        incident_id=payload.incident_id,
        accepted_count=accepted,
        rejected_count=rejected,
    )

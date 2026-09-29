import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Incident, Evidence
from ..schemas.otlp import (
    OtlpTracesPayload,
    OtlpIngestResponse,
    parse_otlp_attributes,
)
from ..agent import EmbeddingClient, format_evidence_for_embedding

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/otlp", tags=["OpenTelemetry"])

# Regex pattern for scrubbing credentials, keys, and tokens
SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|secret|token|auth|credential|api[_-]?key|private[_-]?key)",
    re.IGNORECASE,
)
BEARER_TOKEN_PATTERN = re.compile(
    r"Bearer\s+[A-Za-z0-9\-._~+/]+=*",
    re.IGNORECASE,
)

def scrub_sensitive_data(attrs: Dict[str, Any]) -> Dict[str, Any]:
    """Redacts passwords, tokens, API keys, and Authorization headers."""
    scrubbed = {}
    for k, v in attrs.items():
        if SENSITIVE_KEY_PATTERN.search(k):
            scrubbed[k] = "[REDACTED]"
        elif isinstance(v, str) and BEARER_TOKEN_PATTERN.search(v):
            scrubbed[k] = BEARER_TOKEN_PATTERN.sub("Bearer [REDACTED]", v)
        elif isinstance(v, dict):
            scrubbed[k] = scrub_sensitive_data(v)
        else:
            scrubbed[k] = v
    return scrubbed

def extract_span_message(span_name: str, service_name: str, status_message: Optional[str], events: List[Dict[str, Any]]) -> str:
    """Extracts a clear, informative message for RAG evidence reasoning."""
    for event in events:
        if event.get("name") == "exception":
            attrs = event.get("attributes", {})
            exc_type = attrs.get("exception.type", "Exception")
            exc_msg = attrs.get("exception.message", "Unknown error")
            return f"Span '{span_name}' failed: {exc_type}: {exc_msg}"

    if status_message and status_message.strip():
        return f"Span '{span_name}': {status_message.strip()}"

    return f"Span '{span_name}' executed on service '{service_name}'"

@router.post("/v1/traces", response_model=OtlpIngestResponse, status_code=status.HTTP_202_ACCEPTED)
@router.post("/traces", response_model=OtlpIngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_otlp_traces(payload: OtlpTracesPayload, db: Session = Depends(get_db)):
    """
    Ingests OTLP JSON formatted trace spans sent by the OpenTelemetry Collector.
    Normalizes traces into the Evidence model, prevents replay duplicates, scrubs
    sensitive credentials, and links to incidents when explicit context is present.
    """
    accepted = 0
    rejected = 0
    associated = 0
    unassociated = 0
    new_evidence: List[Evidence] = []
    seen_evidence_ids = set()

    for resource_span in payload.resourceSpans:
        res_attrs = parse_otlp_attributes(resource_span.resource.attributes) if resource_span.resource else {}
        service_name = res_attrs.get("service.name", "unknown_service")

        for scope_span in resource_span.scopeSpans:
            for span in scope_span.spans:
                try:
                    span_id = span.spanId
                    evidence_id = f"ev_span_{span_id}"

                    if evidence_id in seen_evidence_ids:
                        accepted += 1
                        continue

                    existing = db.get(Evidence, evidence_id)
                    if existing:
                        accepted += 1
                        if existing.incident_id:
                            associated += 1
                        else:
                            unassociated += 1
                        continue

                    seen_evidence_ids.add(evidence_id)

                    span_attrs = parse_otlp_attributes(span.attributes)
                    # Use span-level service.name override if provided
                    current_service = span_attrs.get("service.name", service_name)

                    # Timestamp parsing: convert nanoseconds to UTC datetime
                    if span.startTimeUnixNano:
                        ts_seconds = int(span.startTimeUnixNano) / 1e9
                        ts = datetime.fromtimestamp(ts_seconds, tz=timezone.utc)
                    else:
                        ts = datetime.now(timezone.utc)

                    # Parse events (such as exceptions)
                    parsed_events = []
                    for ev in span.events or []:
                        ev_attrs = parse_otlp_attributes(ev.attributes)
                        parsed_events.append({
                            "name": ev.name,
                            "time_nano": ev.timeUnixNano,
                            "attributes": scrub_sensitive_data(ev_attrs),
                        })

                    # Determine severity and status
                    status_code = span.status.code if span.status else 0
                    status_msg = span.status.message if span.status else ""
                    # 2 represents STATUS_CODE_ERROR in OTLP
                    is_error = status_code in (2, "2", "STATUS_CODE_ERROR") or any(e["name"] == "exception" for e in parsed_events)
                    severity = "error" if is_error else "info"

                    message = extract_span_message(span.name, current_service, status_msg, parsed_events)

                    # Incident association: check for explicit incident ID in span or resource attributes
                    target_incident_id = (
                        span_attrs.get("incident.id")
                        or span_attrs.get("incident_id")
                        or res_attrs.get("incident.id")
                        or res_attrs.get("incident_id")
                    )

                    linked_incident_id: Optional[str] = None
                    if target_incident_id:
                        incident = db.get(Incident, str(target_incident_id))
                        if incident:
                            linked_incident_id = incident.id
                            associated += 1
                        else:
                            # Target incident doesn't exist; preserve telemetry unlinked rather than dropping
                            unassociated += 1
                    else:
                        unassociated += 1

                    # Metadata compilation with sensitive data scrubbed
                    metadata = {
                        "span_id": span_id,
                        "parent_span_id": span.parentSpanId,
                        "span_name": span.name,
                        "span_kind": span.kind,
                        "status_code": status_code,
                        "status_message": status_msg,
                        "attributes": scrub_sensitive_data(span_attrs),
                        "resource_attributes": scrub_sensitive_data(res_attrs),
                        "events": parsed_events,
                    }

                    ev_model = Evidence(
                        id=evidence_id,
                        incident_id=linked_incident_id,
                        type="trace",
                        timestamp=ts,
                        service=current_service,
                        severity=severity,
                        message=message,
                        trace_id=span.traceId,
                        source="otel",
                        metadata_json=metadata,
                    )
                    new_evidence.append(ev_model)
                    accepted += 1
                except Exception as exc:
                    logger.error("Failed to parse span %s: %s", getattr(span, "spanId", "unknown"), exc)
                    rejected += 1

    if new_evidence:
        # Generate embeddings if EmbeddingClient is operational
        try:
            client = EmbeddingClient(timeout_seconds=5.0)
            texts = [format_evidence_for_embedding(ev) for ev in new_evidence]
            embeddings = await client.generate_embeddings_batch(texts)
            for ev, emb in zip(new_evidence, embeddings):
                ev.embedding = emb
        except Exception as exc:
            logger.debug("Skipping inline embedding for OTLP spans: %s", exc)

        for ev in new_evidence:
            db.add(ev)
        db.commit()

    return OtlpIngestResponse(
        accepted_spans=accepted,
        rejected_spans=rejected,
        associated_spans=associated,
        unassociated_spans=unassociated,
    )

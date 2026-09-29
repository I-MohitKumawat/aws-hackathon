import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import Incident, Evidence
from ..schemas.otlp import (
    OtlpTracesPayload,
    OtlpIngestResponse,
    OtlpLogsPayload,
    OtlpLogsIngestResponse,
    OtlpMetricsPayload,
    OtlpMetricsIngestResponse,
    parse_otlp_attributes,
    parse_otlp_value,
)
from ..agent import EmbeddingClient, format_evidence_for_embedding

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/otlp", tags=["OpenTelemetry"])

# Regex pattern for scrubbing credentials, keys, and tokens
SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|secret|token|auth|credential|api[_-]?key|private[_-]?key|card|cvv|credit)",
    re.IGNORECASE,
)
BEARER_TOKEN_PATTERN = re.compile(
    r"Bearer\s+[A-Za-z0-9\-._~+/]+=*",
    re.IGNORECASE,
)
PASSWORD_VALUE_PATTERN = re.compile(
    r"(password|passwd|pwd|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+",
    re.IGNORECASE,
)

def scrub_sensitive_text(text: str) -> str:
    """Redacts bearer tokens, passwords, and sensitive key-values embedded in text messages."""
    if not text or not isinstance(text, str):
        return text
    scrubbed = BEARER_TOKEN_PATTERN.sub("Bearer [REDACTED]", text)
    scrubbed = PASSWORD_VALUE_PATTERN.sub(r"\1=[REDACTED]", scrubbed)
    return scrubbed

def scrub_sensitive_data(attrs: Dict[str, Any]) -> Dict[str, Any]:
    """Redacts passwords, tokens, API keys, and Authorization headers."""
    scrubbed = {}
    for k, v in attrs.items():
        if SENSITIVE_KEY_PATTERN.search(k):
            scrubbed[k] = "[REDACTED]"
        elif isinstance(v, str):
            scrubbed[k] = scrub_sensitive_text(v)
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
        for ev in new_evidence:
            db.add(ev)
        db.commit()

    return OtlpIngestResponse(
        accepted_spans=accepted,
        rejected_spans=rejected,
        associated_spans=associated,
        unassociated_spans=unassociated,
    )

def map_log_severity(severity_text: Optional[str], severity_number: Optional[Union[int, str]]) -> str:
    """Maps OTLP severity text or severity number to standard evidence severity."""
    if severity_text:
        st = severity_text.strip().lower()
        if any(term in st for term in ("fatal", "crit")):
            return "critical"
        if "error" in st:
            return "error"
        if "warn" in st:
            return "warning"
        if "info" in st:
            return "info"
        if any(term in st for term in ("debug", "trace")):
            return "info"

    if severity_number is not None:
        try:
            sn = int(severity_number)
            if sn >= 21:
                return "critical"
            if sn >= 17:
                return "error"
            if sn >= 13:
                return "warning"
            return "info"
        except (ValueError, TypeError):
            pass

    return "info"

def extract_log_message(body: Any) -> str:
    """Extracts a clear log message string from OTLP AnyValue body."""
    parsed = parse_otlp_value(body)
    if isinstance(parsed, dict):
        if "message" in parsed:
            return str(parsed["message"])
        return json.dumps(parsed)
    return str(parsed) if parsed is not None else ""

@router.post("/v1/logs", response_model=OtlpLogsIngestResponse, status_code=status.HTTP_202_ACCEPTED)
@router.post("/logs", response_model=OtlpLogsIngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_otlp_logs(payload: OtlpLogsPayload, db: Session = Depends(get_db)):
    """
    Ingests OTLP JSON formatted log records sent by the OpenTelemetry Collector.
    Normalizes logs into the Evidence model, prevents duplicate ingestion, scrubs
    sensitive credentials, and links to incidents when explicit context is present.
    """
    accepted = 0
    rejected = 0
    associated = 0
    unassociated = 0
    new_evidence: List[Evidence] = []
    seen_evidence_ids = set()

    for resource_log in payload.resourceLogs:
        res_attrs = parse_otlp_attributes(resource_log.resource.attributes) if resource_log.resource else {}
        service_name = res_attrs.get("service.name", "unknown_service")

        for scope_log in resource_log.scopeLogs:
            for log_record in scope_log.logRecords:
                try:
                    log_attrs = parse_otlp_attributes(log_record.attributes)
                    current_service = log_attrs.get("service.name", service_name)

                    # Timestamp parsing: convert nanoseconds to UTC datetime
                    if log_record.timeUnixNano:
                        ts_seconds = int(log_record.timeUnixNano) / 1e9
                        try:
                            ts = datetime.fromtimestamp(ts_seconds, tz=timezone.utc)
                        except (ValueError, OverflowError, OSError):
                            ts = datetime.now(timezone.utc)
                    elif log_record.observedTimeUnixNano:
                        ts_seconds = int(log_record.observedTimeUnixNano) / 1e9
                        try:
                            ts = datetime.fromtimestamp(ts_seconds, tz=timezone.utc)
                        except (ValueError, OverflowError, OSError):
                            ts = datetime.now(timezone.utc)
                    else:
                        ts = datetime.now(timezone.utc)

                    message = scrub_sensitive_text(extract_log_message(log_record.body))
                    severity = map_log_severity(log_record.severityText, log_record.severityNumber)

                    # Deduplication ID
                    raw_id_seed = f"{current_service}_{log_record.timeUnixNano}_{log_record.traceId}_{log_record.spanId}_{message}"
                    hash_suffix = hashlib.sha256(raw_id_seed.encode("utf-8")).hexdigest()[:16]
                    evidence_id = f"ev_log_{hash_suffix}"

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

                    # Incident association: check for explicit incident ID in log or resource attributes
                    target_incident_id = (
                        log_attrs.get("incident.id")
                        or log_attrs.get("incident_id")
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
                            unassociated += 1
                    else:
                        unassociated += 1

                    metadata = {
                        "severity_text": log_record.severityText,
                        "severity_number": log_record.severityNumber,
                        "span_id": log_record.spanId,
                        "flags": log_record.flags,
                        "attributes": scrub_sensitive_data(log_attrs),
                        "resource_attributes": scrub_sensitive_data(res_attrs),
                    }

                    ev_model = Evidence(
                        id=evidence_id,
                        incident_id=linked_incident_id,
                        type="log",
                        timestamp=ts,
                        service=current_service,
                        severity=severity,
                        message=message,
                        trace_id=log_record.traceId or None,
                        source="otel",
                        metadata_json=metadata,
                    )
                    new_evidence.append(ev_model)
                    accepted += 1
                except Exception as exc:
                    logger.error("Failed to parse log record: %s", exc)
                    rejected += 1

    if new_evidence:
        for ev in new_evidence:
            db.add(ev)
        db.commit()

    return OtlpLogsIngestResponse(
        accepted_logs=accepted,
        rejected_logs=rejected,
        associated_logs=associated,
        unassociated_logs=unassociated,
    )

@router.post("/v1/metrics", response_model=OtlpMetricsIngestResponse, status_code=status.HTTP_202_ACCEPTED)
@router.post("/metrics", response_model=OtlpMetricsIngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_otlp_metrics(payload: OtlpMetricsPayload, db: Session = Depends(get_db)):
    """
    Ingests OTLP JSON formatted metric records sent by the OpenTelemetry Collector.
    Normalizes metric data points into the Evidence model, prevents duplicate ingestion,
    scrubs sensitive credentials, and links to incidents when explicit context is present.
    """
    accepted = 0
    rejected = 0
    associated = 0
    unassociated = 0
    new_evidence: List[Evidence] = []
    seen_evidence_ids = set()

    for resource_metric in payload.resourceMetrics:
        res_attrs = parse_otlp_attributes(resource_metric.resource.attributes) if resource_metric.resource else {}
        service_name = res_attrs.get("service.name", "unknown_service")

        for scope_metric in resource_metric.scopeMetrics:
            for metric in scope_metric.metrics:
                # Collect data points from gauge, sum, or histogram
                points: List[tuple[str, Any]] = []
                if metric.gauge and metric.gauge.dataPoints:
                    points.extend([("gauge", dp) for dp in metric.gauge.dataPoints])
                if metric.sum and metric.sum.dataPoints:
                    points.extend([("sum", dp) for dp in metric.sum.dataPoints])
                if metric.histogram and metric.histogram.dataPoints:
                    points.extend([("histogram", dp) for dp in metric.histogram.dataPoints])

                for metric_type, dp in points:
                    try:
                        dp_attrs = parse_otlp_attributes(dp.attributes)
                        current_service = dp_attrs.get("service.name", service_name)

                        # Timestamp
                        time_nano = getattr(dp, "timeUnixNano", None) or getattr(dp, "startTimeUnixNano", None)
                        if time_nano:
                            try:
                                ts = datetime.fromtimestamp(int(time_nano) / 1e9, tz=timezone.utc)
                            except (ValueError, OverflowError, OSError):
                                ts = datetime.now(timezone.utc)
                        else:
                            ts = datetime.now(timezone.utc)

                        # Value extraction
                        val = None
                        if hasattr(dp, "asInt") and dp.asInt is not None:
                            val = int(dp.asInt)
                        elif hasattr(dp, "asDouble") and dp.asDouble is not None:
                            val = float(dp.asDouble)
                        elif hasattr(dp, "sum") and dp.sum is not None:
                            val = float(dp.sum)
                        elif hasattr(dp, "count") and dp.count is not None:
                            val = int(dp.count)

                        unit_str = f" {metric.unit}" if metric.unit else ""
                        attr_summary = ", ".join(f"{k}={v}" for k, v in dp_attrs.items() if k not in ("service.name", "incident.id", "incident_id"))
                        attr_str = f" [{attr_summary}]" if attr_summary else ""

                        message = f"Metric '{metric.name}' = {val}{unit_str}{attr_str}".strip()

                        # Severity determination
                        lower_name = metric.name.lower()
                        is_error_metric = any(term in lower_name for term in ("fail", "error", "exhaust", "decline", "out_of_stock"))
                        val_num = float(val) if val is not None else 0.0
                        if is_error_metric and val_num > 0:
                            severity = "error"
                        elif "warning" in lower_name or "throttl" in lower_name:
                            severity = "warning"
                        else:
                            severity = "info"

                        # Deduplication ID
                        raw_id_seed = f"{metric.name}_{current_service}_{time_nano}_{attr_summary}_{val}"
                        hash_suffix = hashlib.sha256(raw_id_seed.encode("utf-8")).hexdigest()[:16]
                        evidence_id = f"ev_metric_{hash_suffix}"

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

                        # Incident association
                        target_incident_id = (
                            dp_attrs.get("incident.id")
                            or dp_attrs.get("incident_id")
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
                                unassociated += 1
                        else:
                            unassociated += 1

                        metadata = {
                            "metric_name": metric.name,
                            "metric_description": metric.description,
                            "metric_unit": metric.unit,
                            "metric_type": metric_type,
                            "value": val,
                            "attributes": scrub_sensitive_data(dp_attrs),
                            "resource_attributes": scrub_sensitive_data(res_attrs),
                        }

                        ev_model = Evidence(
                            id=evidence_id,
                            incident_id=linked_incident_id,
                            type="metric",
                            timestamp=ts,
                            service=current_service,
                            severity=severity,
                            message=message,
                            trace_id=None,
                            source="otel",
                            metadata_json=metadata,
                        )
                        new_evidence.append(ev_model)
                        accepted += 1
                    except Exception as exc:
                        logger.error("Failed to parse metric data point: %s", exc)
                        rejected += 1

    if new_evidence:
        for ev in new_evidence:
            db.add(ev)
        db.commit()

    return OtlpMetricsIngestResponse(
        accepted_metrics=accepted,
        rejected_metrics=rejected,
        associated_metrics=associated,
        unassociated_metrics=unassociated,
    )

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel
from sqlalchemy import select, and_, or_, func
from sqlalchemy.orm import Session
from fastapi import BackgroundTasks

from ..config import settings
from ..models import Incident, Evidence, InvestigationJob
from .investigation_service import execute_investigation

logger = logging.getLogger(__name__)

CRITICAL_ERROR_PATTERNS = [
    "connection pool timeout",
    "connectionpooltimeouterror",
    "outofstockerror",
    "paymentgatewayerror",
    "card_issuer_declined",
    "database connection",
    "deadlock detected",
    "out of memory",
    "unhandled exception",
    "fatal",
]

class RuleEvaluationResult(BaseModel):
    triggered: bool
    rule_name: str
    service: str
    severity: str
    title: str
    reason: str
    time_window_start: datetime
    time_window_end: datetime
    sample_evidence_ids: List[str] = []

class DetectionService:
    """
    Deterministic rule-based incident detection and multi-signal telemetry correlation engine.
    Continuously monitors unlinked traces, logs, and metrics to:
    1. Detect operational failures (critical logs, repeated failures, elevated error rates, latency spikes).
    2. Prevent duplicate incident storms via deduplication windows.
    3. Auto-correlate related traces, logs, and metrics across microservices using shared trace IDs.
    4. Provide controlled auto-investigation triggering with strict concurrency guards.
    """

    def __init__(
        self,
        window_seconds: Optional[int] = None,
        error_count_threshold: Optional[int] = None,
        error_rate_threshold: Optional[float] = None,
        latency_threshold_ms: Optional[float] = None,
        dedup_window_seconds: Optional[int] = None,
    ):
        self.window_seconds = window_seconds or settings.DETECTION_WINDOW_SECONDS
        self.error_count_threshold = error_count_threshold or settings.DETECTION_ERROR_COUNT_THRESHOLD
        self.error_rate_threshold = error_rate_threshold or settings.DETECTION_ERROR_RATE_THRESHOLD
        self.latency_threshold_ms = latency_threshold_ms or settings.DETECTION_LATENCY_MS_THRESHOLD
        self.dedup_window_seconds = dedup_window_seconds or settings.DETECTION_DEDUPLICATION_WINDOW_SECONDS

    # -------------------------------------------------------------------------
    # Detection Rules
    # -------------------------------------------------------------------------

    def evaluate_critical_error_logs(
        self, service: str, logs: List[Evidence], window_start: datetime, window_end: datetime
    ) -> Optional[RuleEvaluationResult]:
        """
        Rule 1: Critical Error Log Rule
        Fires when error/fatal logs occur matching critical failure keywords.
        """
        critical_logs: List[Evidence] = []
        for l in logs:
            msg_lower = (l.message or "").lower()
            is_critical = (
                l.severity in ["error", "fatal"]
                or any(pattern in msg_lower for pattern in CRITICAL_ERROR_PATTERNS)
            )
            if is_critical and l.severity in ["error", "fatal", "critical"]:
                critical_logs.append(l)

        if not critical_logs:
            return None

        sample = critical_logs[0]
        # Sanitize reason to not expose long payload dumps
        clean_msg = sample.message.replace("\n", " ")[:120]
        return RuleEvaluationResult(
            triggered=True,
            rule_name="critical_error_log",
            service=service,
            severity="critical",
            title=f"[AUTO] Critical Error Alert on {service}",
            reason=f"Critical error log detected on service '{service}': \"{clean_msg}\"",
            time_window_start=window_start,
            time_window_end=window_end,
            sample_evidence_ids=[ev.id for ev in critical_logs[:5]],
        )

    def evaluate_repeated_service_failures(
        self, service: str, traces: List[Evidence], window_start: datetime, window_end: datetime
    ) -> Optional[RuleEvaluationResult]:
        """
        Rule 2: Repeated Service Failures Rule
        Fires when count of failed spans for a service meets or exceeds threshold.
        """
        failed_spans: List[Evidence] = []
        for t in traces:
            status_code = t.metadata_json.get("http.status_code") or t.metadata_json.get("status_code")
            has_error = (
                t.severity == "error"
                or t.metadata_json.get("error") is True
                or t.metadata_json.get("error.type") is not None
                or (isinstance(status_code, int) and status_code >= 500)
            )
            if has_error:
                failed_spans.append(t)

        if len(failed_spans) >= self.error_count_threshold:
            return RuleEvaluationResult(
                triggered=True,
                rule_name="repeated_service_failures",
                service=service,
                severity="high",
                title=f"[AUTO] Repeated Service Failures on {service}",
                reason=f"Detected {len(failed_spans)} failed operations on service '{service}' within {self.window_seconds}s (threshold: {self.error_count_threshold}).",
                time_window_start=window_start,
                time_window_end=window_end,
                sample_evidence_ids=[ev.id for ev in failed_spans[:5]],
            )
        return None

    def evaluate_elevated_error_rate(
        self, service: str, traces: List[Evidence], window_start: datetime, window_end: datetime
    ) -> Optional[RuleEvaluationResult]:
        """
        Rule 3: Elevated Error Rate Rule
        Fires when ratio of failed spans to total spans exceeds threshold (min 4 requests).
        """
        if len(traces) < 4:
            return None

        failed_count = sum(
            1
            for t in traces
            if t.severity == "error"
            or t.metadata_json.get("error") is True
            or (isinstance(t.metadata_json.get("http.status_code"), int) and t.metadata_json.get("http.status_code") >= 500)
        )
        rate = failed_count / len(traces)
        if rate >= self.error_rate_threshold and failed_count >= 2:
            return RuleEvaluationResult(
                triggered=True,
                rule_name="elevated_error_rate",
                service=service,
                severity="high",
                title=f"[AUTO] High Error Rate ({rate:.0%}) on {service}",
                reason=f"Operation error rate on service '{service}' reached {rate:.1%} ({failed_count}/{len(traces)} spans failed), exceeding threshold of {self.error_rate_threshold:.0%}.",
                time_window_start=window_start,
                time_window_end=window_end,
                sample_evidence_ids=[t.id for t in traces if t.severity == "error"][:5],
            )
        return None

    def evaluate_sustained_latency(
        self, service: str, traces: List[Evidence], window_start: datetime, window_end: datetime
    ) -> Optional[RuleEvaluationResult]:
        """
        Rule 4: Sustained Latency Increase Rule
        Fires when average operation duration exceeds latency threshold (min 3 spans).
        """
        durations = []
        for t in traces:
            dur = t.metadata_json.get("duration_ms")
            if dur is not None and isinstance(dur, (int, float)) and dur > 0:
                durations.append(dur)

        if len(durations) >= 3:
            avg_dur = sum(durations) / len(durations)
            if avg_dur >= self.latency_threshold_ms:
                return RuleEvaluationResult(
                    triggered=True,
                    rule_name="sustained_latency_increase",
                    service=service,
                    severity="medium",
                    title=f"[AUTO] Latency Spike ({avg_dur:.0f}ms) on {service}",
                    reason=f"Average latency for service '{service}' is {avg_dur:.1f}ms over {len(durations)} spans (threshold: {self.latency_threshold_ms:.1f}ms).",
                    time_window_start=window_start,
                    time_window_end=window_end,
                    sample_evidence_ids=[t.id for t in traces][:5],
                )
        return None

    # -------------------------------------------------------------------------
    # Deduplication & Incident Grouping
    # -------------------------------------------------------------------------

    def find_active_incident(
        self, db: Session, service: str, rule_name: str, now: datetime
    ) -> Optional[Incident]:
        """
        Finds an open or investigating incident for the same service and failure condition
        created within the deduplication window to prevent duplicate incident creation.
        """
        cutoff = now - timedelta(seconds=self.dedup_window_seconds)
        stmt = (
            select(Incident)
            .where(
                Incident.service == service,
                Incident.status.in_(["open", "investigating"]),
                or_(
                    Incident.created_at >= cutoff,
                    Incident.detection_rule == rule_name,
                ),
            )
            .order_by(Incident.created_at.desc())
        )
        return db.execute(stmt).scalars().first()

    # -------------------------------------------------------------------------
    # Telemetry Correlation
    # -------------------------------------------------------------------------

    def correlate_telemetry(
        self,
        db: Session,
        incident: Incident,
        triggering_evidence: List[Evidence],
        window_start: datetime,
        window_end: datetime,
    ) -> int:
        """
        Associates unlinked evidence items with the incident:
        1. All unlinked items from the affected service within the time window.
        2. Any unlinked cross-service spans/logs that share a trace_id with the triggering evidence.
        """
        associated_count = 0
        trace_ids = {ev.trace_id for ev in triggering_evidence if ev.trace_id}

        # 1. Unlinked evidence for the same service in the window
        unlinked_service_query = select(Evidence).where(
            Evidence.incident_id.is_(None),
            Evidence.service == incident.service,
            Evidence.timestamp >= window_start,
            Evidence.timestamp <= window_end,
        )
        service_items = list(db.execute(unlinked_service_query).scalars().all())
        for item in service_items:
            item.incident_id = incident.id
            if item.trace_id:
                trace_ids.add(item.trace_id)
            associated_count += 1

        # 2. Cross-service correlation: any unlinked spans/logs sharing trace_id
        if trace_ids:
            unlinked_trace_query = select(Evidence).where(
                Evidence.incident_id.is_(None),
                Evidence.trace_id.in_(list(trace_ids)),
            )
            trace_items = list(db.execute(unlinked_trace_query).scalars().all())
            for item in trace_items:
                item.incident_id = incident.id
                associated_count += 1

        db.commit()
        return associated_count

    # -------------------------------------------------------------------------
    # Investigation Concurrency Guard
    # -------------------------------------------------------------------------

    def trigger_investigation_if_configured(
        self,
        db: Session,
        incident: Incident,
        background_tasks: Optional[BackgroundTasks] = None,
    ) -> Optional[str]:
        """
        Triggers an AI investigation for a newly detected incident if configured,
        strictly preventing duplicate or concurrent jobs for the same active incident.
        """
        if not settings.AUTO_INVESTIGATE_ON_DETECTION:
            return None

        # Concurrency guard: check for existing active job
        existing_job = db.execute(
            select(InvestigationJob)
            .where(
                InvestigationJob.incident_id == incident.id,
                InvestigationJob.status.in_(["queued", "running"]),
            )
            .order_by(InvestigationJob.created_at.desc())
        ).scalars().first()

        if existing_job:
            logger.info("Active investigation job %s already running for incident %s; skipping duplicate", existing_job.job_id, incident.id)
            return existing_job.job_id

        # Update incident status
        incident.status = "investigating"
        job = InvestigationJob(
            job_id=f"job_{uuid.uuid4().hex[:8]}",
            incident_id=incident.id,
            status="queued",
            stage="queued",
            progress=0,
            created_at=datetime.now(timezone.utc),
        )
        db.add(job)
        db.commit()
        db.refresh(job)

        if background_tasks:
            background_tasks.add_task(execute_investigation, job.job_id)
        else:
            # If no background tasks context (e.g. OTLP worker thread), spawn task safely
            import asyncio
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(execute_investigation(job.job_id))
            except RuntimeError:
                # No running event loop
                pass

        logger.info("Auto-investigation job %s queued for auto-detected incident %s", job.job_id, incident.id)
        return job.job_id

    # -------------------------------------------------------------------------
    # Main Evaluation Loop
    # -------------------------------------------------------------------------

    def evaluate_and_create_incidents(
        self,
        db: Session,
        window_seconds: Optional[int] = None,
        background_tasks: Optional[BackgroundTasks] = None,
    ) -> List[Incident]:
        """
        Scans recent unlinked telemetry across all services and evaluates detection rules.
        Creates or updates incidents and returns the list of affected incidents.
        """
        sec = window_seconds or self.window_seconds
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(seconds=sec)
        window_end = now + timedelta(seconds=120)

        # Query all unlinked evidence in the time window
        unlinked_query = (
            select(Evidence)
            .where(
                Evidence.incident_id.is_(None),
                Evidence.timestamp >= window_start,
                Evidence.timestamp <= window_end,
            )
            .order_by(Evidence.timestamp.asc())
        )
        unlinked_items = list(db.execute(unlinked_query).scalars().all())
        if not unlinked_items:
            return []

        # Group unlinked items by service
        items_by_service: Dict[str, Dict[str, List[Evidence]]] = {}
        for item in unlinked_items:
            if item.service not in items_by_service:
                items_by_service[item.service] = {"trace": [], "log": [], "metric": []}
            if item.type in items_by_service[item.service]:
                items_by_service[item.service][item.type].append(item)

        affected_incidents: List[Incident] = []

        for service, signals in items_by_service.items():
            traces = signals["trace"]
            logs = signals["log"]

            # Evaluate rules in priority order: Critical Logs -> Repeated Failures -> High Error Rate -> Latency
            results: List[RuleEvaluationResult] = []

            crit_res = self.evaluate_critical_error_logs(service, logs, window_start, window_end)
            if crit_res:
                results.append(crit_res)

            rep_res = self.evaluate_repeated_service_failures(service, traces, window_start, window_end)
            if rep_res:
                results.append(rep_res)

            err_rate_res = self.evaluate_elevated_error_rate(service, traces, window_start, window_end)
            if err_rate_res:
                results.append(err_rate_res)

            lat_res = self.evaluate_sustained_latency(service, traces, window_start, window_end)
            if lat_res:
                results.append(lat_res)

            if not results:
                continue

            # Pick highest severity rule result
            severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
            results.sort(key=lambda r: severity_order.get(r.severity, 99))
            primary_result = results[0]

            # Check deduplication: does an active incident already exist for this service?
            active_incident = self.find_active_incident(db, service, primary_result.rule_name, now)

            if active_incident:
                logger.info(
                    "Continuing failure detected on service '%s' (rule: %s). Attaching to existing active incident %s",
                    service,
                    primary_result.rule_name,
                    active_incident.id,
                )
                # Group & correlate unlinked telemetry to existing incident
                all_service_unlinked = traces + logs + signals["metric"]
                self.correlate_telemetry(db, active_incident, all_service_unlinked, window_start, window_end)
                affected_incidents.append(active_incident)
            else:
                # Create brand-new auto-detected incident
                new_incident = Incident(
                    id=str(uuid.uuid4()),
                    title=primary_result.title,
                    service=service,
                    severity=primary_result.severity,
                    status="open",
                    source="auto_detected",
                    detection_rule=primary_result.rule_name,
                    detection_reason=primary_result.reason,
                    description=(
                        f"Automatically detected by rule '{primary_result.rule_name}'. "
                        f"{primary_result.reason}"
                    ),
                    started_at=primary_result.time_window_start,
                    created_at=now,
                )
                db.add(new_incident)
                db.commit()
                db.refresh(new_incident)

                logger.info(
                    "Automatically created Incident %s: '%s' for service '%s' via rule '%s'",
                    new_incident.id,
                    new_incident.title,
                    service,
                    primary_result.rule_name,
                )

                # Correlate all unlinked telemetry for this service and shared trace IDs
                all_service_unlinked = traces + logs + signals["metric"]
                self.correlate_telemetry(db, new_incident, all_service_unlinked, window_start, window_end)

                # Controlled auto-investigation
                self.trigger_investigation_if_configured(db, new_incident, background_tasks)

                affected_incidents.append(new_incident)

        return affected_incidents


# Global singleton instance for easy import
detection_service = DetectionService()

from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple
from backend.app.models import Incident, Evidence

CONTROLLED_INCIDENT: Dict[str, Any] = {
    "id": "inc_checkout_500",
    "title": "Checkout service HTTP 500 errors post-deployment",
    "service": "checkout",
    "severity": "high",
    "status": "open",
    "started_at": "2026-09-29T09:27:00Z",
    "ended_at": None,
    "description": "Checkout service latency and 500 error rate spiked shortly following deployment v2.1.0.",
}

CONTROLLED_EVIDENCE: List[Dict[str, Any]] = [
    {
        "id": "ev_dep_01",
        "incident_id": "inc_checkout_500",
        "type": "deployment",
        "timestamp": "2026-09-29T09:25:00Z",
        "service": "checkout",
        "severity": "info",
        "message": "Deployment checkout-v2.1.0 completed by CI/CD pipeline",
        "trace_id": None,
        "source": "otel",
        "metadata": {"version": "v2.1.0", "commit": "a1b2c3d"},
    },
    {
        "id": "ev_log_01",
        "incident_id": "inc_checkout_500",
        "type": "log",
        "timestamp": "2026-09-29T09:28:15Z",
        "service": "checkout",
        "severity": "error",
        "message": "Connection pool timeout: unable to obtain connection to postgresql://db-primary:5432/checkout within 5000ms",
        "trace_id": "trace_chk_98124",
        "source": "otel",
        "metadata": {"error_code": "POOL_TIMEOUT", "pool_size": 20},
    },
    {
        "id": "ev_met_01",
        "incident_id": "inc_checkout_500",
        "type": "metric",
        "timestamp": "2026-09-29T09:29:00Z",
        "service": "checkout",
        "severity": "error",
        "message": "HTTP 5xx error rate spiked to 18.5% of total requests (threshold: 1.0%)",
        "trace_id": None,
        "source": "otel",
        "metadata": {"metric": "http_requests_5xx_rate", "value": 18.5, "threshold": 1.0},
    },
    {
        "id": "ev_met_02",
        "incident_id": "inc_checkout_500",
        "type": "metric",
        "timestamp": "2026-09-29T09:30:00Z",
        "service": "postgres",
        "severity": "warn",
        "message": "PostgreSQL active connections reached 98/100 (98% pool utilization)",
        "trace_id": None,
        "source": "otel",
        "metadata": {"metric": "pg_stat_activity_connections", "active": 98, "max": 100},
    },
]

def get_controlled_incident_models() -> Tuple[Incident, List[Evidence]]:
    """Helper to return SQLAlchemy model instances for database seeding."""
    started_dt = datetime.fromisoformat(CONTROLLED_INCIDENT["started_at"].replace("Z", "+00:00"))
    incident = Incident(
        id=CONTROLLED_INCIDENT["id"],
        title=CONTROLLED_INCIDENT["title"],
        service=CONTROLLED_INCIDENT["service"],
        severity=CONTROLLED_INCIDENT["severity"],
        status=CONTROLLED_INCIDENT["status"],
        description=CONTROLLED_INCIDENT["description"],
        started_at=started_dt,
        created_at=datetime.now(timezone.utc),
    )

    evidence_models = []
    for ev in CONTROLLED_EVIDENCE:
        ts_dt = datetime.fromisoformat(ev["timestamp"].replace("Z", "+00:00"))
        evidence_models.append(
            Evidence(
                id=ev["id"],
                incident_id=ev["incident_id"],
                type=ev["type"],
                timestamp=ts_dt,
                service=ev["service"],
                severity=ev["severity"],
                message=ev["message"],
                trace_id=ev["trace_id"],
                source=ev["source"],
                metadata_json=ev["metadata"],
                created_at=datetime.now(timezone.utc),
            )
        )

    return incident, evidence_models

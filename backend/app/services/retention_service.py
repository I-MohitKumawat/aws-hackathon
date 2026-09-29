from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Set
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..models import Evidence, Incident, InvestigationReport, InvestigationJob

def get_all_cited_evidence_ids(db: Session) -> Set[str]:
    """
    Extracts all evidence IDs cited in any investigation report across all incidents.
    """
    reports = db.execute(select(InvestigationReport)).scalars().all()
    cited_ids = set()
    for rep in reports:
        for hyp in (rep.hypotheses_json or []):
            if isinstance(hyp, dict):
                for ev_id in hyp.get("supporting_evidence", []):
                    cited_ids.add(ev_id)
                for ev_id in hyp.get("contradicting_evidence", []):
                    cited_ids.add(ev_id)
    return cited_ids

def cleanup_stale_telemetry(
    db: Session,
    retention_hours: int = 168,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Purges stale telemetry older than retention_hours while strictly preserving:
    1. Telemetry associated with active incidents (status == 'open' or 'investigating').
    2. Telemetry cited in historical investigation reports (supporting or contradicting).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
    cited_evidence_ids = get_all_cited_evidence_ids(db)

    # Active incident IDs whose evidence must NEVER be touched
    active_incidents = db.execute(
        select(Incident.id).where(Incident.status.in_(["open", "investigating"]))
    ).scalars().all()
    active_incident_ids = set(active_incidents)

    # Candidate evidence older than retention cutoff
    stale_evidence = db.execute(
        select(Evidence).where(Evidence.timestamp < cutoff)
    ).scalars().all()

    to_delete = []
    deleted_unlinked = 0
    deleted_resolved = 0
    preserved_active = 0
    preserved_cited = 0

    for ev in stale_evidence:
        # Protect active incident evidence
        if ev.incident_id and ev.incident_id in active_incident_ids:
            preserved_active += 1
            continue

        # Protect cited evidence in historical reports
        if ev.id in cited_evidence_ids:
            preserved_cited += 1
            continue

        if ev.incident_id is None:
            deleted_unlinked += 1
        else:
            deleted_resolved += 1
        to_delete.append(ev)

    if not dry_run and to_delete:
        for ev in to_delete:
            db.delete(ev)
        db.commit()

    return {
        "cutoff": cutoff.isoformat(),
        "retention_hours": retention_hours,
        "dry_run": dry_run,
        "deleted_unlinked_count": deleted_unlinked,
        "deleted_resolved_count": deleted_resolved,
        "total_deleted": deleted_unlinked + deleted_resolved,
        "preserved_active_incident_count": preserved_active,
        "preserved_cited_evidence_count": preserved_cited,
    }

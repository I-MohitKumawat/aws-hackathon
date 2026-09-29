from typing import Optional
from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..config import settings
from ..core.auth import Role, require_roles
from ..services.retention_service import cleanup_stale_telemetry

router = APIRouter(prefix="/admin", tags=["Administration"])

class CleanupResponse(BaseModel):
    cutoff: str
    retention_hours: int
    dry_run: bool
    deleted_unlinked_count: int
    deleted_resolved_count: int
    total_deleted: int
    preserved_active_incident_count: int
    preserved_cited_evidence_count: int

@router.post("/cleanup", response_model=CleanupResponse, status_code=status.HTTP_200_OK)
def trigger_telemetry_cleanup(
    retention_hours: Optional[int] = Query(default=None, ge=1),
    dry_run: bool = Query(default=False),
    db: Session = Depends(get_db),
    _role: str = Depends(require_roles([Role.ADMIN.value])),
):
    """
    Executes telemetry retention cleanup:
    - Purges unlinked telemetry and telemetry from resolved incidents older than retention window.
    - Strictly preserves telemetry associated with active (open/investigating) incidents.
    - Strictly preserves telemetry cited in historical investigation reports.
    """
    hours = retention_hours if retention_hours is not None else settings.RETENTION_TELEMETRY_HOURS
    result = cleanup_stale_telemetry(db, retention_hours=hours, dry_run=dry_run)
    return CleanupResponse(**result)

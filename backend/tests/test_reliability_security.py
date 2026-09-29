import uuid
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.main import app
from backend.app.config import settings
from backend.app.database import Base, get_db
from backend.app.models import Incident, Evidence, InvestigationJob, InvestigationReport
from backend.app.services.investigation_service import recover_orphaned_jobs, get_investigation_semaphore
from backend.app.services.retention_service import cleanup_stale_telemetry

# In-memory database fixture
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=engine)
    app.dependency_overrides[get_db] = override_get_db
    yield
    app.dependency_overrides.pop(get_db, None)
    Base.metadata.drop_all(bind=engine)

@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()

# -----------------------------------------------------------------------------
# 1. Authentication & RBAC Tests
# -----------------------------------------------------------------------------

def test_unauthenticated_request_rejected_401():
    client = TestClient(app)  # No auth headers
    res = client.get("/api/v1/incidents")
    assert res.status_code == 401
    data = res.json()
    assert data["error"]["code"] == "UNAUTHORIZED"

def test_invalid_api_key_rejected_401():
    client = TestClient(app, headers={"X-API-Key": "invalid-token-xyz"})
    res = client.get("/api/v1/incidents")
    assert res.status_code == 401
    data = res.json()
    assert data["error"]["code"] == "INVALID_CREDENTIALS"

def test_bearer_token_authentication():
    client = TestClient(app, headers={"Authorization": "Bearer dev-viewer-key"})
    res = client.get("/api/v1/incidents")
    assert res.status_code == 200

def test_viewer_role_access_boundaries(db):
    inc = Incident(
        id="inc_test_viewer",
        title="Viewer Test Incident",
        service="checkout",
        severity="medium",
        status="open",
        started_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    db.add(inc)
    db.commit()

    viewer_client = TestClient(app, headers={"X-API-Key": "dev-viewer-key"})

    # Read operations should succeed
    res_list = viewer_client.get("/api/v1/incidents")
    assert res_list.status_code == 200

    res_get = viewer_client.get(f"/api/v1/incidents/{inc.id}")
    assert res_get.status_code == 200

    # Write / mutate operations must be rejected with 403 Forbidden
    res_create = viewer_client.post(
        "/api/v1/incidents",
        json={
            "title": "Unauthorized Inc",
            "service": "payment",
            "severity": "low",
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert res_create.status_code == 403
    assert res_create.json()["error"]["code"] == "FORBIDDEN"

    res_resolve = viewer_client.post(f"/api/v1/incidents/{inc.id}/resolve")
    assert res_resolve.status_code == 403

    res_investigate = viewer_client.post(f"/api/v1/incidents/{inc.id}/investigations")
    assert res_investigate.status_code == 403

    res_admin = viewer_client.post("/api/v1/admin/cleanup")
    assert res_admin.status_code == 403

def test_investigator_role_access(db):
    investigator_client = TestClient(app, headers={"X-API-Key": "dev-investigator-key"})

    # Investigator can create incident
    res_create = investigator_client.post(
        "/api/v1/incidents",
        json={
            "title": "Investigator Incident",
            "service": "inventory",
            "severity": "high",
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert res_create.status_code == 201
    inc_id = res_create.json()["id"]

    # Investigator can resolve incident
    res_resolve = investigator_client.post(f"/api/v1/incidents/{inc_id}/resolve")
    assert res_resolve.status_code == 200
    assert res_resolve.json()["status"] == "resolved"

    # Investigator CANNOT access admin cleanup
    res_admin = investigator_client.post("/api/v1/admin/cleanup")
    assert res_admin.status_code == 403

def test_admin_role_access():
    admin_client = TestClient(app, headers={"X-API-Key": "dev-admin-key"})
    res_clean = admin_client.post("/api/v1/admin/cleanup?dry_run=true")
    assert res_clean.status_code == 200
    assert "deleted_unlinked_count" in res_clean.json()

def test_telemetry_collector_role_access(db):
    inc = Incident(
        id="inc_collector_test",
        title="Collector Incident",
        service="checkout",
        severity="high",
        status="open",
        started_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    db.add(inc)
    db.commit()

    collector_client = TestClient(app, headers={"X-API-Key": "dev-collector-key"})

    # Telemetry ingestion endpoint is authorized
    telemetry_payload = {
        "incident_id": inc.id,
        "evidence": [
            {
                "type": "log",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "service": "checkout",
                "severity": "error",
                "message": "Collector authorized ingest test",
            }
        ],
    }
    res = collector_client.post("/api/v1/telemetry", json=telemetry_payload)
    assert res.status_code == 202
    assert res.json()["accepted_count"] == 1

    # Collector cannot mutate incidents directly
    res_inc = collector_client.post(
        "/api/v1/incidents",
        json={
            "title": "Unauthorized",
            "service": "checkout",
            "severity": "low",
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert res_inc.status_code == 403

# -----------------------------------------------------------------------------
# 2. Telemetry Resilience & Request Limits
# -----------------------------------------------------------------------------

def test_telemetry_batch_size_limit_exceeded_422(db):
    inc = Incident(
        id="inc_batch_test",
        title="Batch Test",
        service="checkout",
        severity="medium",
        status="open",
        started_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    db.add(inc)
    db.commit()

    admin_client = TestClient(app, headers={"X-API-Key": "dev-admin-key"})

    # Generate 1001 items (limit is 1000)
    oversized_evidence = [
        {
            "type": "log",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "service": "checkout",
            "severity": "info",
            "message": f"Log item {i}",
        }
        for i in range(1001)
    ]

    res = admin_client.post(
        "/api/v1/telemetry",
        json={"incident_id": inc.id, "evidence": oversized_evidence},
    )
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "BATCH_SIZE_EXCEEDED"

def test_payload_size_limit_middleware_413():
    # Simulate oversized Content-Length header exceeding MAX_REQUEST_BODY_BYTES (10MB)
    client = TestClient(app, headers={"X-API-Key": "dev-admin-key", "Content-Length": "15000000"})
    res = client.post(
        "/api/v1/incidents",
        json={
            "title": "Test",
            "service": "test",
            "severity": "low",
            "started_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    assert res.status_code == 413
    assert res.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"

# -----------------------------------------------------------------------------
# 3. Investigation Reliability & Startup Recovery
# -----------------------------------------------------------------------------

def test_backend_restart_orphaned_job_recovery(db):
    inc = Incident(
        id="inc_recover_test",
        title="Restart Incident",
        service="checkout",
        severity="high",
        status="investigating",
        started_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    db.add(inc)

    # Job 1: In 'running' state when backend restarted
    job1 = InvestigationJob(
        job_id="job_orphaned_running",
        incident_id=inc.id,
        status="running",
        stage="retrieving_evidence",
        progress=20,
        retry_count=0,
        max_retries=2,
        created_at=datetime.now(timezone.utc),
    )
    # Job 2: In 'queued' state
    job2 = InvestigationJob(
        job_id="job_orphaned_queued",
        incident_id=inc.id,
        status="queued",
        stage="queued",
        progress=0,
        retry_count=0,
        max_retries=2,
        created_at=datetime.now(timezone.utc),
    )
    db.add(job1)
    db.add(job2)
    db.commit()

    # Trigger recovery function
    stats = recover_orphaned_jobs(db)
    assert stats["requeued"] == 2
    assert stats["aborted"] == 0

    # Both jobs should now be requeued with retry_count incremented
    db.refresh(job1)
    db.refresh(job2)
    assert job1.status == "queued"
    assert job1.retry_count == 1
    assert job1.stage == "requeued_after_restart"

    assert job2.status == "queued"
    assert job2.retry_count == 1

def test_investigation_retry_exhaustion_on_restart(db):
    inc = Incident(
        id="inc_exhaust_test",
        title="Retry Exhaust Incident",
        service="payment",
        severity="critical",
        status="investigating",
        started_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
    )
    db.add(inc)

    # Job already at maximum retries (2/2)
    job = InvestigationJob(
        job_id="job_exhausted",
        incident_id=inc.id,
        status="running",
        stage="analyzing_evidence",
        progress=50,
        retry_count=2,
        max_retries=2,
        created_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.commit()

    stats = recover_orphaned_jobs(db)
    assert stats["aborted"] == 1

    db.refresh(job)
    assert job.status == "failed"
    assert job.stage == "aborted_retry_limit"
    assert "maximum retry limit" in job.error
    assert job.completed_at is not None

def test_investigation_concurrency_semaphore():
    sem = get_investigation_semaphore()
    assert sem is not None
    # Verify bounded semaphore limit matches settings
    assert sem._value <= settings.MAX_CONCURRENT_INVESTIGATIONS

# -----------------------------------------------------------------------------
# 4. Data Retention & Citation Safety
# -----------------------------------------------------------------------------

def test_data_retention_preserves_active_and_cited_evidence(db):
    past_time = datetime.now(timezone.utc) - timedelta(hours=48)

    # 1. Active incident (open)
    active_inc = Incident(
        id="inc_active_retention",
        title="Active Incident",
        service="checkout",
        severity="high",
        status="open",
        started_at=past_time,
        created_at=past_time,
    )
    # 2. Resolved incident
    resolved_inc = Incident(
        id="inc_resolved_retention",
        title="Resolved Incident",
        service="inventory",
        severity="low",
        status="resolved",
        started_at=past_time,
        created_at=past_time,
        ended_at=past_time,
    )
    db.add(active_inc)
    db.add(resolved_inc)

    # Evidence items
    ev_unlinked = Evidence(
        id="ev_stale_unlinked",
        type="log",
        timestamp=past_time,
        service="checkout",
        severity="info",
        message="Stale unlinked message",
    )
    ev_resolved = Evidence(
        id="ev_stale_resolved",
        incident_id=resolved_inc.id,
        type="log",
        timestamp=past_time,
        service="inventory",
        severity="info",
        message="Stale resolved message",
    )
    ev_active = Evidence(
        id="ev_active_preserved",
        incident_id=active_inc.id,
        type="log",
        timestamp=past_time,
        service="checkout",
        severity="error",
        message="Active incident message (MUST PRESERVE)",
    )
    ev_cited = Evidence(
        id="ev_cited_preserved",
        incident_id=resolved_inc.id,
        type="trace",
        timestamp=past_time,
        service="inventory",
        severity="error",
        message="Cited in historical report (MUST PRESERVE)",
    )
    db.add(ev_unlinked)
    db.add(ev_resolved)
    db.add(ev_active)
    db.add(ev_cited)

    # Historical Report citing ev_cited_preserved
    job = InvestigationJob(
        job_id="job_report_retention",
        incident_id=resolved_inc.id,
        status="completed",
        created_at=past_time,
    )
    db.add(job)
    report = InvestigationReport(
        id="rep_retention_test",
        job_id=job.job_id,
        incident_id=resolved_inc.id,
        status="completed",
        summary="Historical summary",
        hypotheses_json=[
            {
                "id": "hyp_1",
                "description": "Stock exhausted",
                "status": "supported",
                "supporting_evidence": ["ev_cited_preserved"],
                "contradicting_evidence": [],
            }
        ],
        created_at=past_time,
    )
    db.add(report)
    db.commit()

    # Run cleanup with 24h retention window
    result = cleanup_stale_telemetry(db, retention_hours=24, dry_run=False)

    assert result["total_deleted"] == 2
    assert result["deleted_unlinked_count"] == 1
    assert result["deleted_resolved_count"] == 1
    assert result["preserved_active_incident_count"] == 1
    assert result["preserved_cited_evidence_count"] == 1

    # Verify database contents
    assert db.get(Evidence, "ev_stale_unlinked") is None
    assert db.get(Evidence, "ev_stale_resolved") is None
    assert db.get(Evidence, "ev_active_preserved") is not None
    assert db.get(Evidence, "ev_cited_preserved") is not None

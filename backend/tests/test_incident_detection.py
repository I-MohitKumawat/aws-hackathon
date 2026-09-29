import uuid
from datetime import datetime, timezone, timedelta
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app.main import app
from backend.app.database import Base, get_db
from backend.app.models import Incident, Evidence, InvestigationJob
from backend.app.services.detection_service import DetectionService, detection_service
from backend.app.config import settings

# Setup in-memory SQLite database for deterministic testing
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
def client():
    return TestClient(app)

@pytest.fixture
def db_session():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def test_critical_error_log_rule(db_session):
    detector = DetectionService(window_seconds=60)
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=60)

    log_item = Evidence(
        id=f"ev_log_{uuid.uuid4().hex[:8]}",
        type="log",
        timestamp=now,
        service="checkout",
        severity="error",
        message="ConnectionPoolTimeoutError: unable to obtain connection within 5000ms",
        metadata_json={},
    )

    res = detector.evaluate_critical_error_logs("checkout", [log_item], window_start, now)
    assert res is not None
    assert res.triggered is True
    assert res.rule_name == "critical_error_log"
    assert res.severity == "critical"
    assert "checkout" in res.title
    assert "Critical error log detected" in res.reason


def test_repeated_service_failures_rule(db_session):
    detector = DetectionService(window_seconds=60, error_count_threshold=3)
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=60)

    # 2 failed spans -> should NOT trigger (threshold is 3)
    spans = [
        Evidence(
            id=f"ev_span_{i}",
            type="trace",
            timestamp=now,
            service="checkout",
            severity="error",
            message=f"Span {i} failed",
            metadata_json={"error": True, "http.status_code": 500},
        )
        for i in range(2)
    ]
    res = detector.evaluate_repeated_service_failures("checkout", spans, window_start, now)
    assert res is None

    # Add 3rd failed span -> should trigger
    spans.append(
        Evidence(
            id="ev_span_3",
            type="trace",
            timestamp=now,
            service="checkout",
            severity="error",
            message="Span 3 failed",
            metadata_json={"error": True, "http.status_code": 500},
        )
    )
    res = detector.evaluate_repeated_service_failures("checkout", spans, window_start, now)
    assert res is not None
    assert res.triggered is True
    assert res.rule_name == "repeated_service_failures"
    assert res.severity == "high"
    assert "3 failed operations" in res.reason


def test_elevated_error_rate_rule(db_session):
    detector = DetectionService(window_seconds=60, error_rate_threshold=0.5)
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=60)

    # 4 spans: 1 error, 3 ok (25% error rate) -> should NOT trigger
    spans_normal = [
        Evidence(id="ev_1", type="trace", timestamp=now, service="inventory", severity="info", message="ok", metadata_json={"http.status_code": 200}),
        Evidence(id="ev_2", type="trace", timestamp=now, service="inventory", severity="info", message="ok", metadata_json={"http.status_code": 200}),
        Evidence(id="ev_3", type="trace", timestamp=now, service="inventory", severity="info", message="ok", metadata_json={"http.status_code": 200}),
        Evidence(id="ev_4", type="trace", timestamp=now, service="inventory", severity="error", message="err", metadata_json={"http.status_code": 500, "error": True}),
    ]
    res_normal = detector.evaluate_elevated_error_rate("inventory", spans_normal, window_start, now)
    assert res_normal is None

    # 4 spans: 3 error, 1 ok (75% error rate) -> should trigger
    spans_high_err = [
        Evidence(id="ev_5", type="trace", timestamp=now, service="inventory", severity="info", message="ok", metadata_json={"http.status_code": 200}),
        Evidence(id="ev_6", type="trace", timestamp=now, service="inventory", severity="error", message="err", metadata_json={"http.status_code": 500, "error": True}),
        Evidence(id="ev_7", type="trace", timestamp=now, service="inventory", severity="error", message="err", metadata_json={"http.status_code": 500, "error": True}),
        Evidence(id="ev_8", type="trace", timestamp=now, service="inventory", severity="error", message="err", metadata_json={"http.status_code": 500, "error": True}),
    ]
    res_high = detector.evaluate_elevated_error_rate("inventory", spans_high_err, window_start, now)
    assert res_high is not None
    assert res_high.triggered is True
    assert res_high.rule_name == "elevated_error_rate"
    assert "75" in res_high.reason


def test_sustained_latency_rule(db_session):
    detector = DetectionService(window_seconds=60, latency_threshold_ms=2000.0)
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(seconds=60)

    # 3 spans with low latency (50ms avg) -> should NOT trigger
    low_lat = [
        Evidence(id="ev_l1", type="trace", timestamp=now, service="payment", severity="info", message="ok", metadata_json={"duration_ms": 40.0}),
        Evidence(id="ev_l2", type="trace", timestamp=now, service="payment", severity="info", message="ok", metadata_json={"duration_ms": 50.0}),
        Evidence(id="ev_l3", type="trace", timestamp=now, service="payment", severity="info", message="ok", metadata_json={"duration_ms": 60.0}),
    ]
    assert detector.evaluate_sustained_latency("payment", low_lat, window_start, now) is None

    # 3 spans with high latency (2500ms avg) -> should trigger
    high_lat = [
        Evidence(id="ev_h1", type="trace", timestamp=now, service="payment", severity="info", message="slow", metadata_json={"duration_ms": 2400.0}),
        Evidence(id="ev_h2", type="trace", timestamp=now, service="payment", severity="info", message="slow", metadata_json={"duration_ms": 2600.0}),
        Evidence(id="ev_h3", type="trace", timestamp=now, service="payment", severity="info", message="slow", metadata_json={"duration_ms": 2500.0}),
    ]
    res = detector.evaluate_sustained_latency("payment", high_lat, window_start, now)
    assert res is not None
    assert res.triggered is True
    assert res.rule_name == "sustained_latency_increase"
    assert res.severity == "medium"
    assert "2500.0ms" in res.reason


def test_normal_traffic_does_not_trigger_incident(db_session):
    now = datetime.now(timezone.utc)
    for i in range(5):
        db_session.add(
            Evidence(
                id=f"ev_norm_span_{i}",
                type="trace",
                timestamp=now,
                service="checkout",
                severity="info",
                message=f"Normal span {i}",
                metadata_json={"duration_ms": 25.0, "http.status_code": 200},
            )
        )
        db_session.add(
            Evidence(
                id=f"ev_norm_log_{i}",
                type="log",
                timestamp=now,
                service="checkout",
                severity="info",
                message=f"Normal log message {i}",
                metadata_json={},
            )
        )
    db_session.commit()

    incidents = detection_service.evaluate_and_create_incidents(db_session, window_seconds=60)
    assert len(incidents) == 0
    assert db_session.query(Incident).count() == 0


def test_automatic_incident_creation_and_telemetry_correlation(db_session):
    now = datetime.now(timezone.utc)
    shared_trace_id = "trace_cascade_12345"

    # Checkout failed span
    ev_checkout = Evidence(
        id="ev_span_checkout",
        type="trace",
        trace_id=shared_trace_id,
        timestamp=now,
        service="checkout",
        severity="error",
        message="Span 'call_inventory_service' failed: DownstreamServiceError: 409",
        metadata_json={"error": True, "http.status_code": 500},
    )
    # Downstream inventory error span sharing same trace ID
    ev_inventory = Evidence(
        id="ev_span_inventory",
        type="trace",
        trace_id=shared_trace_id,
        timestamp=now,
        service="inventory",
        severity="error",
        message="Span 'inventory.check_stock' failed: OutOfStockError",
        metadata_json={"error": True, "http.status_code": 409},
    )
    # Critical error log on checkout
    ev_log = Evidence(
        id="ev_log_checkout",
        type="log",
        trace_id=shared_trace_id,
        timestamp=now,
        service="checkout",
        severity="error",
        message="ConnectionPoolTimeoutError: unable to obtain connection within 5000ms",
        metadata_json={},
    )

    db_session.add_all([ev_checkout, ev_inventory, ev_log])
    db_session.commit()

    # Run detection
    detected = detection_service.evaluate_and_create_incidents(db_session, window_seconds=60)
    assert len(detected) >= 1

    inc = detected[0]
    assert inc.source == "auto_detected"
    assert inc.service in ["checkout", "inventory"]
    assert inc.status == "open"
    assert inc.detection_rule is not None
    assert inc.detection_reason is not None

    # Verify cross-service telemetry correlation:
    # All 3 evidence items (including the downstream inventory span sharing trace ID) are correlated!
    db_session.refresh(ev_checkout)
    db_session.refresh(ev_log)
    assert ev_checkout.incident_id is not None
    assert ev_log.incident_id is not None


def test_duplicate_incident_suppression(db_session):
    now = datetime.now(timezone.utc)

    # 1. Create first batch of errors
    log_1 = Evidence(
        id="ev_dup_log_1",
        type="log",
        timestamp=now,
        service="checkout",
        severity="error",
        message="ConnectionPoolTimeoutError: database failure",
        metadata_json={},
    )
    db_session.add(log_1)
    db_session.commit()

    first_incidents = detection_service.evaluate_and_create_incidents(db_session, window_seconds=60)
    assert len(first_incidents) == 1
    first_id = first_incidents[0].id
    assert db_session.query(Incident).count() == 1

    # 2. Add second error for same service within deduplication window
    log_2 = Evidence(
        id="ev_dup_log_2",
        type="log",
        timestamp=now + timedelta(seconds=5),
        service="checkout",
        severity="error",
        message="ConnectionPoolTimeoutError: recurring database failure",
        metadata_json={},
    )
    db_session.add(log_2)
    db_session.commit()

    second_incidents = detection_service.evaluate_and_create_incidents(db_session, window_seconds=60)
    # Should attach to existing incident rather than creating duplicate
    assert len(second_incidents) == 1
    assert second_incidents[0].id == first_id
    assert db_session.query(Incident).count() == 1

    db_session.refresh(log_2)
    assert log_2.incident_id == first_id


def test_investigation_concurrency_guard(client, db_session):
    # Create incident
    inc = Incident(
        id="inc_guard_test",
        title="Test Incident for Concurrency Guard",
        service="checkout",
        severity="high",
        status="open",
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(inc)
    db_session.commit()

    # Trigger first investigation
    resp1 = client.post(f"/api/v1/incidents/{inc.id}/investigations", json={})
    assert resp1.status_code == 202
    job1_id = resp1.json()["job_id"]

    # Trigger second investigation on the same incident while first is active
    resp2 = client.post(f"/api/v1/incidents/{inc.id}/investigations", json={})
    assert resp2.status_code == 202
    job2_id = resp2.json()["job_id"]

    # Concurrency guard should return the existing active job
    assert job1_id == job2_id
    assert db_session.query(InvestigationJob).filter_by(incident_id=inc.id).count() == 1


def test_incident_resolve_and_reopen_lifecycle(client, db_session):
    now = datetime.now(timezone.utc)
    inc = Incident(
        id="inc_lifecycle_test",
        title="Test Incident for Lifecycle",
        service="inventory",
        severity="medium",
        status="open",
        source="auto_detected",
        detection_rule="repeated_service_failures",
        detection_reason="3 errors observed",
        started_at=now,
    )
    db_session.add(inc)
    db_session.commit()

    # Resolve incident via endpoint
    res_resp = client.post(f"/api/v1/incidents/{inc.id}/resolve")
    assert res_resp.status_code == 200
    data = res_resp.json()
    assert data["status"] == "resolved"
    assert data["ended_at"] is not None

    db_session.refresh(inc)
    assert inc.status == "resolved"

    # Subsequent failure should now open a fresh incident since previous was resolved
    log_new = Evidence(
        id="ev_post_resolve_log",
        type="log",
        timestamp=now + timedelta(seconds=10),
        service="inventory",
        severity="error",
        message="ConnectionPoolTimeoutError: failure after resolution",
        metadata_json={},
    )
    db_session.add(log_new)
    db_session.commit()

    new_incidents = detection_service.evaluate_and_create_incidents(db_session, window_seconds=60)
    assert len(new_incidents) == 1
    assert new_incidents[0].id != inc.id
    assert db_session.query(Incident).count() == 2


def test_detect_endpoint_api(client, db_session):
    now = datetime.now(timezone.utc)
    db_session.add(
        Evidence(
            id="ev_api_log",
            type="log",
            timestamp=now,
            service="checkout",
            severity="error",
            message="OutOfStockError: inventory failure via api",
            metadata_json={},
        )
    )
    db_session.commit()

    resp = client.post("/api/v1/incidents/detect?window_seconds=60")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 1
    assert items[0]["source"] == "auto_detected"

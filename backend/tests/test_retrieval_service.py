from datetime import datetime, timezone, timedelta
from typing import List
import pytest
from unittest.mock import AsyncMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.app.database import Base
from backend.app.models import Incident, Evidence, InvestigationJob
from backend.app.services.retrieval_service import (
    retrieve_evidence_for_investigation,
    cosine_similarity,
)
from backend.app.agent.embedding_client import (
    EmbeddingClient,
    EmbeddingConnectionError,
)

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()

@pytest.fixture
def mock_embedding_client():
    client = AsyncMock(spec=EmbeddingClient)
    client.generate_embedding.return_value = [0.1] * 384
    client.generate_embeddings_batch.return_value = [[0.1] * 384]
    return client

def _make_vector(val: float) -> List[float]:
    """Creates a normalized or directional 384-dimension test vector."""
    return [val] * 384

@pytest.mark.asyncio
async def test_cosine_similarity():
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    v3 = [0.0, 1.0, 0.0]
    v4 = [-1.0, 0.0, 0.0]
    assert pytest.approx(cosine_similarity(v1, v2), 0.001) == 1.0
    assert pytest.approx(cosine_similarity(v1, v3), 0.001) == 0.0
    assert pytest.approx(cosine_similarity(v1, v4), 0.001) == -1.0
    assert cosine_similarity([], v1) == 0.0
    assert cosine_similarity([0.0, 0.0], [0.0, 0.0]) == 0.0

@pytest.mark.asyncio
async def test_retrieval_incident_isolation(db_session, mock_embedding_client):
    now = datetime.now(timezone.utc)
    inc_a = Incident(id="inc_a", title="Incident A", service="order-service", severity="critical", started_at=now)
    inc_b = Incident(id="inc_b", title="Incident B", service="auth-service", severity="high", started_at=now)
    db_session.add_all([inc_a, inc_b])
    db_session.commit()

    # Evidence for A and B in the same time window
    ev_a1 = Evidence(id="ev_a1", incident_id="inc_a", type="log", timestamp=now, service="order-service", message="Error A")
    ev_b1 = Evidence(id="ev_b1", incident_id="inc_b", type="log", timestamp=now, service="auth-service", message="Error B")
    db_session.add_all([ev_a1, ev_b1])
    db_session.commit()

    job_a = InvestigationJob(job_id="job_a", incident_id="inc_a", status="running", stage="retrieving_evidence", progress=20)
    db_session.add(job_a)
    db_session.commit()

    retrieved = await retrieve_evidence_for_investigation(
        db=db_session,
        incident=inc_a,
        job=job_a,
        top_k=10,
        embedding_client=mock_embedding_client,
    )

    retrieved_ids = [ev.id for ev in retrieved]
    assert "ev_a1" in retrieved_ids
    assert "ev_b1" not in retrieved_ids
    assert all(ev.incident_id == "inc_a" for ev in retrieved)

@pytest.mark.asyncio
async def test_retrieval_time_window_boundaries(db_session, mock_embedding_client):
    now = datetime.now(timezone.utc)
    inc = Incident(id="inc_window", title="Window Incident", service="payment", severity="critical", started_at=now)
    db_session.add(inc)

    # 4 items: before window, inside window 1, inside window 2, after window
    ev_before = Evidence(id="ev_before", incident_id=inc.id, type="log", timestamp=now - timedelta(hours=2), service="payment", message="Before")
    ev_in1 = Evidence(id="ev_in1", incident_id=inc.id, type="log", timestamp=now - timedelta(minutes=15), service="payment", message="In 1")
    ev_in2 = Evidence(id="ev_in2", incident_id=inc.id, type="log", timestamp=now - timedelta(minutes=5), service="payment", message="In 2")
    ev_after = Evidence(id="ev_after", incident_id=inc.id, type="log", timestamp=now + timedelta(hours=1), service="payment", message="After")
    db_session.add_all([ev_before, ev_in1, ev_in2, ev_after])
    db_session.commit()

    job = InvestigationJob(
        job_id="job_window",
        incident_id=inc.id,
        status="running",
        stage="retrieving_evidence",
        progress=20,
        time_window_start=now - timedelta(minutes=30),
        time_window_end=now,
    )
    db_session.add(job)
    db_session.commit()

    retrieved = await retrieve_evidence_for_investigation(
        db=db_session,
        incident=inc,
        job=job,
        top_k=10,
        embedding_client=mock_embedding_client,
    )

    retrieved_ids = [ev.id for ev in retrieved]
    assert "ev_in1" in retrieved_ids
    assert "ev_in2" in retrieved_ids
    assert "ev_before" not in retrieved_ids
    assert "ev_after" not in retrieved_ids
    # Verify chronological ordering
    assert retrieved[0].id == "ev_in1"
    assert retrieved[1].id == "ev_in2"

@pytest.mark.asyncio
async def test_retrieval_empty_scope(db_session, mock_embedding_client):
    now = datetime.now(timezone.utc)
    inc = Incident(id="inc_empty", title="Empty Incident", service="cart", severity="low", started_at=now)
    db_session.add(inc)

    job = InvestigationJob(
        job_id="job_empty",
        incident_id=inc.id,
        status="running",
        stage="retrieving_evidence",
        progress=20,
        time_window_start=now - timedelta(minutes=10),
        time_window_end=now,
    )
    db_session.add(job)
    db_session.commit()

    retrieved = await retrieve_evidence_for_investigation(
        db=db_session,
        incident=inc,
        job=job,
        top_k=5,
        embedding_client=mock_embedding_client,
    )
    assert retrieved == []

@pytest.mark.asyncio
async def test_retrieval_within_budget_returns_all(db_session, mock_embedding_client):
    now = datetime.now(timezone.utc)
    inc = Incident(id="inc_small", title="Small Incident", service="api", severity="medium", started_at=now)
    db_session.add(inc)

    ev1 = Evidence(id="ev1", incident_id=inc.id, type="metric", timestamp=now - timedelta(minutes=3), service="api", message="CPU spike")
    ev2 = Evidence(id="ev2", incident_id=inc.id, type="log", timestamp=now - timedelta(minutes=1), service="api", message="OOM killer")
    db_session.add_all([ev1, ev2])
    db_session.commit()

    job = InvestigationJob(job_id="job_small", incident_id=inc.id, status="running", stage="retrieving_evidence", progress=20)
    db_session.add(job)
    db_session.commit()

    retrieved = await retrieve_evidence_for_investigation(
        db=db_session,
        incident=inc,
        job=job,
        top_k=10,
        embedding_client=mock_embedding_client,
    )
    assert len(retrieved) == 2
    assert retrieved[0].id == "ev1"
    assert retrieved[1].id == "ev2"

@pytest.mark.asyncio
async def test_retrieval_semantic_ranking_above_budget(db_session):
    now = datetime.now(timezone.utc)
    inc = Incident(
        id="inc_semantic",
        title="Database connection timeout",
        service="order-service",
        severity="critical",
        description="Pool exhaustion causing HTTP 500",
        started_at=now,
    )
    db_session.add(inc)

    # Incident query vector direction: [1.0, 0.0, ...]
    query_vector = [1.0] + [0.0] * 383

    # Add 10 evidence items:
    # ev_rel_1 and ev_rel_2 have vectors aligned with query ([0.9, 0.0, ...])
    # others have orthogonal vectors ([0.0, 1.0, ...])
    items = []
    for i in range(10):
        t = now - timedelta(minutes=10 - i)
        if i == 3:
            # Highly relevant match
            vec = [0.95] + [0.0] * 383
            items.append(Evidence(id=f"ev_rel_1", incident_id=inc.id, type="log", timestamp=t, service="order-service", message="Pool timeout", embedding=vec))
        elif i == 7:
            # Second relevant match
            vec = [0.85] + [0.0] * 383
            items.append(Evidence(id=f"ev_rel_2", incident_id=inc.id, type="log", timestamp=t, service="order-service", message="Connection refused", embedding=vec))
        else:
            # Unrelated noise
            vec = [0.0, 1.0] + [0.0] * 382
            items.append(Evidence(id=f"ev_noise_{i}", incident_id=inc.id, type="log", timestamp=t, service="order-service", message=f"Routine check {i}", embedding=vec))

    db_session.add_all(items)
    db_session.commit()

    job = InvestigationJob(job_id="job_semantic", incident_id=inc.id, status="running", stage="retrieving_evidence", progress=20)
    db_session.add(job)
    db_session.commit()

    mock_client = AsyncMock(spec=EmbeddingClient)
    mock_client.generate_embedding.return_value = query_vector

    retrieved = await retrieve_evidence_for_investigation(
        db=db_session,
        incident=inc,
        job=job,
        top_k=3,
        embedding_client=mock_client,
    )

    assert len(retrieved) == 3
    retrieved_ids = [ev.id for ev in retrieved]
    # The two highly aligned evidence items must be selected
    assert "ev_rel_1" in retrieved_ids
    assert "ev_rel_2" in retrieved_ids
    # Verify final list is returned chronologically
    timestamps = [ev.timestamp for ev in retrieved]
    assert timestamps == sorted(timestamps)

@pytest.mark.asyncio
async def test_retrieval_high_signal_prioritization(db_session):
    now = datetime.now(timezone.utc)
    inc = Incident(id="inc_hs", title="Service Outage", service="checkout", severity="critical", started_at=now)
    db_session.add(inc)

    # 10 items: 1 deployment, 1 critical error, 8 routine info logs
    items = []
    items.append(Evidence(id="ev_deploy", incident_id=inc.id, type="deployment", timestamp=now - timedelta(minutes=9), service="checkout", severity="info", message="Deployed v2.4.1"))
    items.append(Evidence(id="ev_crit", incident_id=inc.id, type="log", timestamp=now - timedelta(minutes=5), service="checkout", severity="critical", message="CrashLoopBackOff"))
    for i in range(8):
        items.append(Evidence(id=f"ev_info_{i}", incident_id=inc.id, type="log", timestamp=now - timedelta(minutes=8 - i), service="checkout", severity="info", message=f"Heartbeat {i}"))

    db_session.add_all(items)
    db_session.commit()

    job = InvestigationJob(job_id="job_hs", incident_id=inc.id, status="running", stage="retrieving_evidence", progress=20)
    db_session.add(job)
    db_session.commit()

    # Pass client that fails embedding generation to force structured prioritization
    mock_client = AsyncMock(spec=EmbeddingClient)
    mock_client.generate_embedding.side_effect = EmbeddingConnectionError("Ollama unreachable")

    retrieved = await retrieve_evidence_for_investigation(
        db=db_session,
        incident=inc,
        job=job,
        top_k=3,
        embedding_client=mock_client,
    )

    assert len(retrieved) == 3
    retrieved_ids = [ev.id for ev in retrieved]
    # Both high signal items must be included despite top_k=3 limiting total candidates
    assert "ev_deploy" in retrieved_ids
    assert "ev_crit" in retrieved_ids
    # Chronological sort order preserved
    timestamps = [ev.timestamp for ev in retrieved]
    assert timestamps == sorted(timestamps)

@pytest.mark.asyncio
async def test_retrieval_on_the_fly_embedding_enrichment(db_session):
    now = datetime.now(timezone.utc)
    inc = Incident(id="inc_otf", title="API Timeout", service="frontend", severity="high", started_at=now)
    db_session.add(inc)

    # 4 items without embeddings
    items = [
        Evidence(id=f"ev_otf_{i}", incident_id=inc.id, type="log", timestamp=now - timedelta(minutes=5 - i), service="frontend", message=f"Log {i}")
        for i in range(4)
    ]
    db_session.add_all(items)
    db_session.commit()

    job = InvestigationJob(job_id="job_otf", incident_id=inc.id, status="running", stage="retrieving_evidence", progress=20)
    db_session.add(job)
    db_session.commit()

    mock_client = AsyncMock(spec=EmbeddingClient)
    dummy_vec = [0.1] * 384
    mock_client.generate_embeddings_batch.return_value = [dummy_vec] * 4
    mock_client.generate_embedding.return_value = dummy_vec

    retrieved = await retrieve_evidence_for_investigation(
        db=db_session,
        incident=inc,
        job=job,
        top_k=2,
        embedding_client=mock_client,
    )

    assert len(retrieved) == 2
    mock_client.generate_embeddings_batch.assert_called_once()
    # Confirm evidence in DB was updated with embeddings
    refreshed_ev = db_session.get(Evidence, "ev_otf_0")
    assert refreshed_ev.embedding is not None
    assert len(refreshed_ev.embedding) == 384

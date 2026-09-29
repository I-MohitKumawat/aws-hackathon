import logging
import math
from typing import List, Optional, Set
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..config import settings
from ..models import Incident, Evidence, InvestigationJob
from ..agent.embedding_client import (
    EmbeddingClient,
    EmbeddingClientError,
    format_evidence_for_embedding,
)

logger = logging.getLogger(__name__)

def cosine_similarity(v1: List[float], v2: List[float]) -> float:
    """
    Computes cosine similarity between two float vectors.
    Returns value in [-1.0, 1.0], or 0.0 if either vector is zero-magnitude or invalid.
    """
    if not v1 or not v2 or len(v1) != len(v2):
        return 0.0
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 <= 0.0 or norm2 <= 0.0:
        return 0.0
    return dot / (norm1 * norm2)

def is_high_signal_evidence(ev: Evidence) -> bool:
    """
    Identifies high-signal telemetry records (errors, critical alerts, warnings, and deployment events).
    """
    sev = (ev.severity or "").lower()
    ev_type = (ev.type or "").lower()
    return sev in ("error", "critical", "warning", "warn") or ev_type in ("deployment", "event")

def _sort_chronologically(evidence_items: List[Evidence]) -> List[Evidence]:
    """Sorts evidence items chronologically by timestamp ascending."""
    return sorted(evidence_items, key=lambda ev: ev.timestamp)

async def retrieve_evidence_for_investigation(
    db: Session,
    incident: Incident,
    job: InvestigationJob,
    top_k: int = settings.RETRIEVAL_TOP_K,
    embedding_client: Optional[EmbeddingClient] = None,
) -> List[Evidence]:
    """
    Retrieves the most relevant telemetry evidence for an investigation:
    1. Pre-filters strictly by incident_id and time window [time_window_start, time_window_end].
    2. If candidate count <= top_k, returns all candidates sorted chronologically.
    3. Hybrid selection:
       - Prioritizes high-signal items (errors, critical severity, deployment events).
       - Ranks candidates by semantic vector similarity against the incident context.
       - Gracefully falls back to structured priority retrieval if embeddings are unavailable.
    4. Merges selected items and returns them sorted chronologically (timestamp ASC).
    """
    # 1. Base Pre-filtering: Strictly isolate by incident and time-window bounds
    query = select(Evidence).where(Evidence.incident_id == incident.id)
    if job.time_window_start is not None:
        query = query.where(Evidence.timestamp >= job.time_window_start)
    if job.time_window_end is not None:
        query = query.where(Evidence.timestamp <= job.time_window_end)

    candidates: List[Evidence] = list(db.scalars(query.order_by(Evidence.timestamp.asc())).all())

    # If candidates fit within budget, return all of them chronologically
    if len(candidates) <= top_k:
        return candidates

    # 2. Check for missing embeddings and attempt on-the-fly enrichment if client is available
    client = embedding_client or EmbeddingClient()
    unembedded = [ev for ev in candidates if ev.embedding is None]
    if unembedded:
        # Cap batch to at most 50 items to prevent unbounded delays when telemetry volume is high
        unembedded_batch = unembedded[:50]
        try:
            texts = [format_evidence_for_embedding(ev) for ev in unembedded_batch]
            embeddings = await client.generate_embeddings_batch(texts)
            for ev, emb in zip(unembedded_batch, embeddings):
                ev.embedding = emb
            db.commit()
            logger.info("Successfully generated embeddings for %d candidate evidence items on-the-fly.", len(unembedded_batch))
        except Exception as exc:
            logger.warning("Could not generate embeddings on-the-fly for evidence items (%s). Proceeding with fallback.", exc)

    # 3. Construct incident query text and attempt to generate query embedding
    query_text = f"Incident: {incident.title} | Service: {incident.service} | Description: {incident.description or ''}".strip()
    query_vector: Optional[List[float]] = None
    try:
        query_vector = await client.generate_embedding(query_text)
    except Exception as exc:
        logger.warning("Failed to generate incident query embedding (%s). Falling back to structured heuristic retrieval.", exc)
        query_vector = None

    # 4. Fallback Selection when embeddings are unavailable
    if query_vector is None:
        return _fallback_structured_retrieval(candidates, top_k)

    # 5. Vector-assisted hybrid retrieval
    dialect_name = db.bind.dialect.name if db.bind else "sqlite"
    if dialect_name == "postgresql":
        # Native pgvector path in PostgreSQL
        try:
            sql_query = (
                select(Evidence)
                .where(Evidence.incident_id == incident.id)
                .where(Evidence.embedding.isnot(None))
            )
            if job.time_window_start is not None:
                sql_query = sql_query.where(Evidence.timestamp >= job.time_window_start)
            if job.time_window_end is not None:
                sql_query = sql_query.where(Evidence.timestamp <= job.time_window_end)

            semantic_matches = list(
                db.scalars(
                    sql_query.order_by(Evidence.embedding.cosine_distance(query_vector)).limit(top_k)
                ).all()
            )
            return _merge_hybrid_candidates(candidates, semantic_matches, top_k)
        except Exception as exc:
            logger.warning("PostgreSQL pgvector query failed (%s). Falling back to in-memory cosine ranking.", exc)

    # In-memory cosine similarity ranking (SQLite / fallback path)
    return _rank_candidates_in_memory(candidates, query_vector, top_k)

def _merge_hybrid_candidates(
    all_candidates: List[Evidence],
    semantic_matches: List[Evidence],
    top_k: int,
) -> List[Evidence]:
    """
    Merges high-signal items and top semantic vector matches, ensuring budget <= top_k.
    """
    selected_set: Set[str] = set()
    selected_items: List[Evidence] = []

    # Quota for high-signal events (up to top_k // 2)
    high_signal = [ev for ev in all_candidates if is_high_signal_evidence(ev)]
    for ev in high_signal[: max(1, top_k // 2)]:
        if ev.id not in selected_set:
            selected_set.add(ev.id)
            selected_items.append(ev)

    # Fill remaining quota with semantic matches
    for ev in semantic_matches:
        if len(selected_items) >= top_k:
            break
        if ev.id not in selected_set:
            selected_set.add(ev.id)
            selected_items.append(ev)

    # If still below top_k, fill from remaining candidates
    for ev in all_candidates:
        if len(selected_items) >= top_k:
            break
        if ev.id not in selected_set:
            selected_set.add(ev.id)
            selected_items.append(ev)

    return _sort_chronologically(selected_items)

def _rank_candidates_in_memory(
    candidates: List[Evidence],
    query_vector: List[float],
    top_k: int,
) -> List[Evidence]:
    """
    Ranks candidates in memory using cosine similarity with a high-signal boost.
    """
    scored_items = []
    for ev in candidates:
        sim = 0.0
        if ev.embedding is not None:
            sim = cosine_similarity(query_vector, ev.embedding)
        # Boost high-signal items so critical telemetry is prioritized alongside semantic relevance
        boost = 0.35 if is_high_signal_evidence(ev) else 0.0
        scored_items.append((sim + boost, ev))

    # Sort descending by composite score
    scored_items.sort(key=lambda pair: pair[0], reverse=True)
    top_items = [pair[1] for pair in scored_items[:top_k]]
    return _sort_chronologically(top_items)

def _fallback_structured_retrieval(
    candidates: List[Evidence],
    top_k: int,
) -> List[Evidence]:
    """
    Structured fallback selection when vector embeddings are unavailable.
    Prioritizes high-signal items (errors, deployments), then recent evidence.
    """
    high_signal = [ev for ev in candidates if is_high_signal_evidence(ev)]
    other_evidence = [ev for ev in candidates if not is_high_signal_evidence(ev)]

    selected: List[Evidence] = []
    # Include high signal first
    selected.extend(high_signal[:top_k])

    # If slots remain, fill with remaining items (preferring latest items)
    remaining_slots = top_k - len(selected)
    if remaining_slots > 0:
        other_sorted = sorted(other_evidence, key=lambda ev: ev.timestamp, reverse=True)
        selected.extend(other_sorted[:remaining_slots])

    return _sort_chronologically(selected)

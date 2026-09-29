import os
import pytest
from backend.app.agent.embedding_client import EmbeddingClient
from backend.app.services.retrieval_service import cosine_similarity

@pytest.mark.asyncio
async def test_live_embedding_generation():
    """
    Opt-in live integration test that runs against a live local Ollama embedding instance.
    To execute: RUN_LIVE_EMBEDDING=true pytest backend/tests/test_live_embedding.py
    Prerequisite: 'ollama pull all-minilm' must be run on the host.
    """
    if os.environ.get("RUN_LIVE_EMBEDDING", "").lower() != "true":
        pytest.skip("Skipping live embedding test. Set RUN_LIVE_EMBEDDING=true to run against live local Ollama embedding model.")

    client = EmbeddingClient()
    text = "Database connection pool timeout on checkout-service"
    vec = await client.generate_embedding(text)

    assert isinstance(vec, list)
    assert len(vec) == 384
    assert any(x != 0.0 for x in vec)

    # Test batch embedding and similarity discrimination
    query = "Database connection pool timeout on checkout-service"
    relevant_text = "Connection pool exhausted: max limit 100 reached for pgsql replica"
    irrelevant_text = "User updated profile picture successfully in s3 bucket"

    batch = await client.generate_embeddings_batch([query, relevant_text, irrelevant_text])
    assert len(batch) == 3
    assert all(len(v) == 384 for v in batch)

    sim_relevant = cosine_similarity(batch[0], batch[1])
    sim_irrelevant = cosine_similarity(batch[0], batch[2])

    assert sim_relevant > sim_irrelevant

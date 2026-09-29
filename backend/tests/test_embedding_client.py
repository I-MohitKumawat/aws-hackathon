import pytest
import httpx
from unittest.mock import AsyncMock, patch

from backend.app.agent.embedding_client import (
    EmbeddingClient,
    EmbeddingClientError,
    EmbeddingConnectionError,
    EmbeddingTimeoutError,
    EmbeddingModelUnavailableError,
    EmbeddingResponseError,
    format_evidence_for_embedding,
)
from backend.app.models import Evidence

def test_format_evidence_for_embedding_model_object():
    ev = Evidence(
        id="ev_test_1",
        incident_id="inc_1",
        type="log",
        service="order-service",
        severity="error",
        message="Failed to connect to database replica",
        metadata_json={"db_host": "db.prod.internal", "retry_count": 3},
    )
    formatted = format_evidence_for_embedding(ev)
    assert "[LOG]" in formatted
    assert "Service: order-service" in formatted
    assert "Severity: error" in formatted
    assert "Failed to connect to database replica" in formatted
    assert "db_host=db.prod.internal" in formatted

def test_format_evidence_for_embedding_dict():
    ev_dict = {
        "type": "metric",
        "service": "checkout-service",
        "severity": "critical",
        "message": "p99 latency exceeded 4500ms",
        "metadata": {"endpoint": "/checkout", "status_code": 504},
    }
    formatted = format_evidence_for_embedding(ev_dict)
    assert "[METRIC]" in formatted
    assert "Service: checkout-service" in formatted
    assert "Severity: critical" in formatted
    assert "p99 latency exceeded 4500ms" in formatted
    assert "endpoint=/checkout" in formatted

@pytest.mark.asyncio
async def test_embedding_client_empty_batch():
    client = EmbeddingClient()
    result = await client.generate_embeddings_batch([])
    assert result == []

@pytest.mark.asyncio
async def test_embedding_client_success_embed_endpoint():
    mock_response = httpx.Response(
        status_code=200,
        json={
            "model": "bge-small-en-v1.5",
            "embeddings": [
                [0.1] * 384,
                [0.2] * 384,
            ],
        },
        request=httpx.Request("POST", "http://localhost:11434/api/embed"),
    )
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.post.return_value = mock_response

    client = EmbeddingClient(http_client=mock_http)
    embeddings = await client.generate_embeddings_batch(["text 1", "text 2"])

    assert len(embeddings) == 2
    assert len(embeddings[0]) == 384
    assert len(embeddings[1]) == 384
    assert embeddings[0][0] == 0.1

@pytest.mark.asyncio
async def test_embedding_client_single_generate():
    mock_response = httpx.Response(
        status_code=200,
        json={
            "model": "bge-small-en-v1.5",
            "embeddings": [[0.42] * 384],
        },
        request=httpx.Request("POST", "http://localhost:11434/api/embed"),
    )
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.post.return_value = mock_response

    client = EmbeddingClient(http_client=mock_http)
    embedding = await client.generate_embedding("incident query")

    assert len(embedding) == 384
    assert embedding[0] == 0.42

@pytest.mark.asyncio
async def test_embedding_client_legacy_embeddings_fallback():
    # Simulate /api/embed returning 404 (endpoint not supported on older Ollama),
    # then /api/embeddings succeeding
    embed_404 = httpx.Response(
        status_code=404,
        text="404 page not found",
        request=httpx.Request("POST", "http://localhost:11434/api/embed"),
    )
    embeddings_200 = httpx.Response(
        status_code=200,
        json={"embedding": [0.77] * 384},
        request=httpx.Request("POST", "http://localhost:11434/api/embeddings"),
    )

    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.post.side_effect = [embed_404, embeddings_200]

    client = EmbeddingClient(http_client=mock_http)
    result = await client.generate_embeddings_batch(["fallback text"])

    assert len(result) == 1
    assert len(result[0]) == 384
    assert result[0][0] == 0.77

@pytest.mark.asyncio
async def test_embedding_client_model_unavailable_error():
    mock_response = httpx.Response(
        status_code=404,
        text='{"error":"model \\"bge-small-en-v1.5\\" not found, try pulling it first"}',
        request=httpx.Request("POST", "http://localhost:11434/api/embed"),
    )
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.post.return_value = mock_response

    client = EmbeddingClient(http_client=mock_http)
    with pytest.raises(EmbeddingModelUnavailableError) as exc_info:
        await client.generate_embeddings_batch(["test"])

    assert exc_info.value.status_code == 404
    assert "not available in Ollama" in str(exc_info.value)

@pytest.mark.asyncio
async def test_embedding_client_connection_error():
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.post.side_effect = httpx.ConnectError("Connection refused")

    client = EmbeddingClient(http_client=mock_http)
    with pytest.raises(EmbeddingConnectionError) as exc_info:
        await client.generate_embedding("test")

    assert "Failed to connect to Ollama embedding service" in str(exc_info.value)

@pytest.mark.asyncio
async def test_embedding_client_timeout_error():
    mock_http = AsyncMock(spec=httpx.AsyncClient)
    mock_http.post.side_effect = httpx.TimeoutException("Timed out")

    client = EmbeddingClient(http_client=mock_http)
    with pytest.raises(EmbeddingTimeoutError) as exc_info:
        await client.generate_embedding("test")

    assert "timed out after" in str(exc_info.value)

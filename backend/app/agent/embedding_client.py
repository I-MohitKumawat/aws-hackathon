from typing import Optional, List, Dict, Any, Union
import httpx

from ..config import settings

class EmbeddingClientError(Exception):
    """Base exception for Embedding client errors."""
    pass

class EmbeddingConnectionError(EmbeddingClientError):
    """Raised when connection to Ollama embedding service fails."""
    pass

class EmbeddingTimeoutError(EmbeddingClientError):
    """Raised when request to Ollama embedding service times out."""
    pass

class EmbeddingModelUnavailableError(EmbeddingClientError):
    """Raised when the specified embedding model is not found or not pulled."""
    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body

class EmbeddingResponseError(EmbeddingClientError):
    """Raised when Ollama returns an unexpected response structure or HTTP error."""
    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body

def format_evidence_for_embedding(evidence: Any) -> str:
    """
    Constructs a rich text representation of an evidence item for embedding.
    Supports SQLAlchemy Evidence model instances, Pydantic schemas, or dictionaries.
    """
    if isinstance(evidence, dict):
        ev_type = evidence.get("type", "unknown")
        service = evidence.get("service", "unknown")
        severity = evidence.get("severity") or "info"
        message = evidence.get("message", "")
        metadata = evidence.get("metadata_json") or evidence.get("metadata") or {}
    else:
        ev_type = getattr(evidence, "type", "unknown")
        service = getattr(evidence, "service", "unknown")
        severity = getattr(evidence, "severity", None) or "info"
        message = getattr(evidence, "message", "")
        metadata = getattr(evidence, "metadata_json", None) or getattr(evidence, "metadata", None) or {}

    meta_str = ""
    if metadata and isinstance(metadata, dict):
        meta_items = [
            f"{k}={v}" for k, v in metadata.items()
            if v is not None and k not in ("raw_payload", "embedding")
        ]
        if meta_items:
            meta_str = f" | {', '.join(meta_items[:5])}"

    return f"[{str(ev_type).upper()}] Service: {service} | Severity: {severity} | {message}{meta_str}".strip()

class EmbeddingClient:
    """
    HTTP client for generating dense vector embeddings using local Ollama.
    Supports Ollama's modern `/api/embed` endpoint with batch inputs and fallback to `/api/embeddings`.
    """
    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.EMBEDDING_MODEL
        self.timeout_seconds = timeout_seconds or 30.0
        self._external_client = http_client

    async def generate_embeddings_batch(self, texts: List[str]) -> List[List[float]]:
        """
        Generates vector embeddings for a list of input texts.
        Returns a list of float vectors.
        """
        if not texts:
            return []

        client = self._external_client or httpx.AsyncClient(timeout=self.timeout_seconds)
        try:
            # First attempt: modern Ollama /api/embed endpoint
            url = f"{self.base_url}/api/embed"
            payload = {
                "model": self.model,
                "input": texts,
            }
            try:
                response = await client.post(url, json=payload)
            except httpx.ConnectError as exc:
                raise EmbeddingConnectionError(
                    f"Failed to connect to Ollama embedding service at {self.base_url}: {exc}"
                ) from exc
            except httpx.TimeoutException as exc:
                raise EmbeddingTimeoutError(
                    f"Ollama embedding request timed out after {self.timeout_seconds} seconds: {exc}"
                ) from exc

            # Check if /api/embed succeeded
            if response.status_code == 200:
                data = response.json()
                if "embeddings" in data:
                    return data["embeddings"]
                raise EmbeddingResponseError(
                    f"Ollama /api/embed response missing 'embeddings' field: {data}"
                )

            # Check if model is not found
            if response.status_code == 404:
                body_text = response.text.lower()
                if "model" in body_text and ("not found" in body_text or "try pulling" in body_text):
                    raise EmbeddingModelUnavailableError(
                        f"Embedding model '{self.model}' is not available in Ollama: {response.text}",
                        status_code=404,
                        response_body=response.text,
                    )

            # Fallback to legacy /api/embeddings endpoint (per text) if /api/embed endpoint wasn't found (404)
            embeddings: List[List[float]] = []
            for text in texts:
                emb = await self._generate_legacy_single(client, text)
                embeddings.append(emb)
            return embeddings

        except (EmbeddingClientError, httpx.HTTPError):
            raise
        except Exception as exc:
            raise EmbeddingResponseError(f"Unexpected error generating embeddings: {exc}") from exc
        finally:
            if not self._external_client:
                await client.aclose()

    async def _generate_legacy_single(self, client: httpx.AsyncClient, text: str) -> List[float]:
        """
        Fallback call to legacy Ollama /api/embeddings for a single prompt.
        """
        url = f"{self.base_url}/api/embeddings"
        payload = {
            "model": self.model,
            "prompt": text,
        }
        try:
            response = await client.post(url, json=payload)
        except httpx.ConnectError as exc:
            raise EmbeddingConnectionError(
                f"Failed to connect to Ollama embedding service at {self.base_url}: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise EmbeddingTimeoutError(
                f"Ollama embedding request timed out after {self.timeout_seconds} seconds: {exc}"
            ) from exc

        if response.status_code == 404:
            body_text = response.text.lower()
            if "model" in body_text and ("not found" in body_text or "try pulling" in body_text):
                raise EmbeddingModelUnavailableError(
                    f"Embedding model '{self.model}' is not available in Ollama: {response.text}",
                    status_code=404,
                    response_body=response.text,
                )

        if response.status_code != 200:
            raise EmbeddingResponseError(
                f"Ollama legacy embedding failed with HTTP {response.status_code}: {response.text}",
                status_code=response.status_code,
                response_body=response.text,
            )

        data = response.json()
        if "embedding" not in data:
            raise EmbeddingResponseError(
                f"Ollama /api/embeddings response missing 'embedding' field: {data}"
            )
        return data["embedding"]

    async def generate_embedding(self, text: str) -> List[float]:
        """
        Generates a vector embedding for a single text input.
        """
        results = await self.generate_embeddings_batch([text])
        if not results:
            raise EmbeddingResponseError("Ollama returned empty embeddings list for input text")
        return results[0]

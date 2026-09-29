from typing import Optional, Dict, Any
import httpx
from ..config import settings

class OllamaClientError(Exception):
    """Base exception for Ollama client errors."""
    pass

class OllamaConnectionError(OllamaClientError):
    """Raised when connection to Ollama fails."""
    pass

class OllamaTimeoutError(OllamaClientError):
    """Raised when request to Ollama times out."""
    pass

class OllamaResponseError(OllamaClientError):
    """Raised when Ollama returns an error status or invalid envelope."""
    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body

class OllamaClient:
    """
    HTTP client for interacting with a local Ollama instance.
    Uses Ollama's /api/generate endpoint with structured JSON output format.
    """
    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout_seconds: Optional[float] = None,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.LLM_MODEL
        self.timeout_seconds = timeout_seconds or settings.OLLAMA_TIMEOUT_SECONDS
        self._external_client = http_client

    async def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        options: Optional[Dict[str, Any]] = None,
        response_format: Optional[Any] = None,
    ) -> str:
        """
        Sends a single inference request to Ollama using structured JSON or JSON Schema format.
        Returns the raw model response string.
        """
        url = f"{self.base_url}/api/generate"
        payload: Dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": response_format if response_format is not None else "json",
            "options": options or {"temperature": 0.1},
        }
        if system:
            payload["system"] = system

        client = self._external_client or httpx.AsyncClient(timeout=self.timeout_seconds)
        try:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.ConnectError as exc:
            raise OllamaConnectionError(
                f"Failed to connect to Ollama at {self.base_url}. Ensure the service is running: {exc}"
            ) from exc
        except httpx.TimeoutException as exc:
            raise OllamaTimeoutError(
                f"Ollama inference timed out after {self.timeout_seconds} seconds: {exc}"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise OllamaResponseError(
                f"Ollama returned HTTP error status {exc.response.status_code}",
                status_code=exc.response.status_code,
                response_body=exc.response.text,
            ) from exc
        except Exception as exc:
            raise OllamaResponseError(f"Unexpected error communicating with Ollama: {exc}") from exc
        finally:
            if not self._external_client:
                await client.aclose()

        if "response" not in data:
            raise OllamaResponseError(
                f"Ollama response missing required 'response' field: {data}"
            )

        return data["response"]

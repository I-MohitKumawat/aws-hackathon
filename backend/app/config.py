from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    ENVIRONMENT: str = "development"
    DATABASE_URL: str = "sqlite:///./incident_investigator.db"
    BACKEND_HOST: str = "0.0.0.0"
    BACKEND_PORT: int = 8000
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://127.0.0.1:3000"]

    OLLAMA_BASE_URL: str = "http://localhost:11434"
    LLM_MODEL: str = "qwen3:4b"
    OLLAMA_TIMEOUT_SECONDS: float = 300.0
    EMBEDDING_MODEL: str = "all-minilm"
    EMBEDDING_DIMENSION: int = 384
    RETRIEVAL_TOP_K: int = 15

    # Automatic Incident Detection & Correlation
    AUTO_DETECTION_ENABLED: bool = True
    DETECTION_WINDOW_SECONDS: int = 60
    DETECTION_ERROR_COUNT_THRESHOLD: int = 3
    DETECTION_ERROR_RATE_THRESHOLD: float = 0.5
    DETECTION_LATENCY_MS_THRESHOLD: float = 2000.0
    DETECTION_DEDUPLICATION_WINDOW_SECONDS: int = 300
    AUTO_INVESTIGATE_ON_DETECTION: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()

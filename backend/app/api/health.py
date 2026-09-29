import os
from typing import Dict, Any
from fastapi import APIRouter
import httpx
from sqlalchemy import text
from ..config import settings
from ..database import engine

router = APIRouter()

@router.get("/health", tags=["Health"])
def health_check():
    return {
        "status": "ok",
        "environment": settings.ENVIRONMENT,
    }

async def _check_http_service(name: str, urls: list[str]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=2.0) as client:
        for url in urls:
            try:
                res = await client.get(url)
                if res.status_code in (200, 204, 301, 302, 307):
                    return {"status": "healthy", "url": url, "code": res.status_code}
            except Exception:
                continue
    return {"status": "unreachable", "url": urls[0]}

@router.get("/health/services", tags=["Health"])
async def services_health_check():
    """
    Checks live health status across all microservices and infrastructure components
    in the AI Software Incident Investigator ecosystem.
    """
    results: Dict[str, Any] = {}

    # 1. Database
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        results["postgres"] = {"status": "healthy", "component": "Database (PostgreSQL + pgvector)"}
    except Exception as exc:
        results["postgres"] = {"status": "unhealthy", "error": str(exc)}

    # 2. Ollama LLM
    ollama_urls = [f"{settings.OLLAMA_BASE_URL}/api/tags", "http://localhost:11435/api/tags", "http://ollama:11434/api/tags"]
    results["ollama"] = await _check_http_service("ollama", ollama_urls)
    results["ollama"]["component"] = f"LLM & Embeddings ({settings.LLM_MODEL})"

    # 3. Checkout Service
    checkout_urls = ["http://checkout-service:8080/health", "http://localhost:8080/health"]
    results["checkout_service"] = await _check_http_service("checkout", checkout_urls)
    results["checkout_service"]["component"] = "Checkout Coordinator (Port 8080)"

    # 4. Inventory Service
    inventory_urls = ["http://inventory-service:8081/health", "http://localhost:8081/health"]
    results["inventory_service"] = await _check_http_service("inventory", inventory_urls)
    results["inventory_service"]["component"] = "Inventory Service (Port 8081)"

    # 5. Payment Service
    payment_urls = ["http://payment-service:8082/health", "http://localhost:8082/health"]
    results["payment_service"] = await _check_http_service("payment", payment_urls)
    results["payment_service"]["component"] = "Payment Service (Port 8082)"

    # 6. OTel Collector
    collector_urls = ["http://otel-collector:13133/health/status", "http://localhost:13133/health/status"]
    results["otel_collector"] = await _check_http_service("collector", collector_urls)
    results["otel_collector"]["component"] = "OpenTelemetry Collector (Port 4317/4318)"

    # 7. Jaeger
    jaeger_urls = ["http://jaeger:16686", "http://localhost:16686"]
    results["jaeger"] = await _check_http_service("jaeger", jaeger_urls)
    results["jaeger"]["component"] = "Jaeger Distributed Tracing (Port 16686)"

    all_healthy = all(v.get("status") == "healthy" for v in results.values())
    return {
        "status": "healthy" if all_healthy else "degraded",
        "timestamp": os.getenv("CURRENT_TIME") or "",
        "services": results,
    }


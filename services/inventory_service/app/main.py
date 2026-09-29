import os
import time
import uuid
from typing import List, Optional
from fastapi import FastAPI, Header, HTTPException, Query, status
from pydantic import BaseModel

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

# Initialize OpenTelemetry TracerProvider
service_name = os.getenv("OTEL_SERVICE_NAME", "inventory")
service_version = os.getenv("SERVICE_VERSION", "1.0.0")
environment = os.getenv("DEPLOYMENT_ENVIRONMENT", "production")

resource = Resource.create({
    "service.name": service_name,
    "service.version": service_version,
    "deployment.environment": environment,
})

provider = TracerProvider(resource=resource)

otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317")
grpc_endpoint = otlp_endpoint.replace("http://", "").replace("https://", "")
is_insecure = os.getenv("OTEL_EXPORTER_OTLP_INSECURE", "true").lower() in ("true", "1")

otlp_exporter = OTLPSpanExporter(
    endpoint=grpc_endpoint,
    insecure=is_insecure,
)
provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("inventory.service", service_version)

app = FastAPI(
    title="Instrumented Inventory Service",
    description="Microservice managing stock validation and reservations with OpenTelemetry tracing.",
    version=service_version,
)

# Instrument FastAPI automatically (handles incoming W3C traceparent extraction)
FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)

class InventoryOutOfStockError(Exception):
    """Simulated inventory out of stock exception."""
    pass

class ReserveRequest(BaseModel):
    items: List[str] = ["item_alpha", "item_beta"]
    order_id: Optional[str] = None

class ReserveResponse(BaseModel):
    reservation_id: str
    status: str
    items: List[str]
    service: str
    version: str

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": service_name,
        "version": service_version,
        "otlp_endpoint": grpc_endpoint,
    }

@app.post("/inventory/reserve", response_model=ReserveResponse)
def reserve_inventory(
    payload: ReserveRequest,
    simulate_error: bool = Query(default=False),
    x_incident_id: Optional[str] = Header(default=None, alias="X-Incident-Id"),
):
    """
    Validates item availability and reserves inventory.
    Emits child spans and supports controllable out-of-stock failures.
    """
    current_span = trace.get_current_span()
    if x_incident_id and current_span:
        current_span.set_attribute("incident.id", x_incident_id)

    reservation_id = f"res_{uuid.uuid4().hex[:8]}"

    # Span 1: Check Stock Availability
    with tracer.start_as_current_span("inventory.check_stock") as stock_span:
        if x_incident_id:
            stock_span.set_attribute("incident.id", x_incident_id)
        stock_span.set_attribute("inventory.items_count", len(payload.items))
        stock_span.set_attribute("inventory.warehouse", "warehouse-east")

        if simulate_error or "out_of_stock" in payload.items:
            err_msg = f"Inventory allocation failed: Item 'item_beta' is out of stock in warehouse-east (requested {len(payload.items)} items)"
            exc = InventoryOutOfStockError(err_msg)
            stock_span.record_exception(exc)
            stock_span.set_status(Status(StatusCode.ERROR, description=err_msg))
            stock_span.set_attribute("error.type", "OUT_OF_STOCK")
            stock_span.set_attribute("inventory.stock_level", 0)

            if current_span:
                current_span.set_status(Status(StatusCode.ERROR, description=err_msg))
                current_span.set_attribute("error.type", "OUT_OF_STOCK")

            provider.force_flush()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=err_msg,
            )

        stock_span.set_attribute("inventory.stock_available", True)
        time.sleep(0.015)

    # Span 2: Lock and Reserve Items in Warehouse DB
    with tracer.start_as_current_span("inventory.reserve_items") as reserve_span:
        if x_incident_id:
            reserve_span.set_attribute("incident.id", x_incident_id)
        reserve_span.set_attribute("inventory.reservation_id", reservation_id)
        reserve_span.set_attribute("inventory.lock_acquired", True)
        time.sleep(0.02)

    provider.force_flush()

    return ReserveResponse(
        reservation_id=reservation_id,
        status="reserved",
        items=payload.items,
        service=service_name,
        version=service_version,
    )

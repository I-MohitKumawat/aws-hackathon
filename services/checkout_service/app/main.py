import os
import time
import uuid
from typing import Optional
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
service_name = os.getenv("OTEL_SERVICE_NAME", "checkout")
service_version = os.getenv("SERVICE_VERSION", "2.1.0")
environment = os.getenv("DEPLOYMENT_ENVIRONMENT", "production")

resource = Resource.create({
    "service.name": service_name,
    "service.version": service_version,
    "deployment.environment": environment,
})

provider = TracerProvider(resource=resource)

otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317")
# If endpoint has http:// prefix, strip it for grpc
grpc_endpoint = otlp_endpoint.replace("http://", "").replace("https://", "")
is_insecure = os.getenv("OTEL_EXPORTER_OTLP_INSECURE", "true").lower() in ("true", "1")

otlp_exporter = OTLPSpanExporter(
    endpoint=grpc_endpoint,
    insecure=is_insecure,
)
provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("checkout.service", service_version)

app = FastAPI(
    title="Instrumented Checkout Service",
    description="Sample microservice emitting real OpenTelemetry traces for incident investigation testing.",
    version=service_version,
)

# Instrument FastAPI automatically for inbound HTTP request spans
FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)

class ConnectionPoolTimeoutError(Exception):
    """Simulated database connection pool exhaustion exception."""
    pass

class CheckoutRequest(BaseModel):
    items: list[str] = ["item_alpha", "item_beta", "item_gamma"]
    total: float = 149.99

class CheckoutResponse(BaseModel):
    order_id: str
    status: str
    total: float
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

@app.post("/checkout", response_model=CheckoutResponse)
def execute_checkout(
    payload: Optional[CheckoutRequest] = None,
    simulate_error: bool = Query(default=False),
    x_incident_id: Optional[str] = Header(default=None, alias="X-Incident-Id"),
):
    """
    Executes a simulated checkout workflow.
    Emits hierarchical spans and supports controllable connection pool timeout failures.
    """
    current_span = trace.get_current_span()
    if x_incident_id and current_span:
        current_span.set_attribute("incident.id", x_incident_id)

    order_id = f"ord_{uuid.uuid4().hex[:8]}"
    items_count = len(payload.items) if payload else 3
    total_val = payload.total if payload else 149.99

    # Child Span 1: Validate Cart
    with tracer.start_as_current_span("validate_cart") as span:
        if x_incident_id:
            span.set_attribute("incident.id", x_incident_id)
        span.set_attribute("cart.items_count", items_count)
        span.set_attribute("cart.total_amount", total_val)
        time.sleep(0.02)

    # Child Span 2: Database Connection & Operation
    with tracer.start_as_current_span("db.acquire_connection") as db_span:
        if x_incident_id:
            db_span.set_attribute("incident.id", x_incident_id)
        db_span.set_attribute("db.system", "postgresql")
        db_span.set_attribute("db.pool.max", 20)

        if simulate_error:
            # Simulate failure: pool exhaustion timeout
            err_msg = "Connection pool timeout: unable to obtain connection to postgresql://db-primary:5432/checkout within 5000ms"
            exc = ConnectionPoolTimeoutError(err_msg)
            db_span.record_exception(exc)
            db_span.set_status(Status(StatusCode.ERROR, description=err_msg))
            db_span.set_attribute("error.type", "POOL_TIMEOUT")
            db_span.set_attribute("db.pool.active", 20)

            if current_span:
                current_span.set_status(Status(StatusCode.ERROR, description=err_msg))
                current_span.set_attribute("error.type", "POOL_TIMEOUT")

            # Force flushing spans immediately before raising error
            provider.force_flush()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=err_msg,
            )

        db_span.set_attribute("db.connection.reused", True)
        time.sleep(0.01)

    # Child Span 3: Payment Processing
    with tracer.start_as_current_span("process_payment") as pay_span:
        if x_incident_id:
            pay_span.set_attribute("incident.id", x_incident_id)
        pay_span.set_attribute("payment.provider", "stripe")
        pay_span.set_attribute("payment.status", "succeeded")
        time.sleep(0.03)

    # Flush spans
    provider.force_flush()

    return CheckoutResponse(
        order_id=order_id,
        status="completed",
        total=total_val,
        service=service_name,
        version=service_version,
    )

@app.post("/checkout/fail")
def fail_checkout(x_incident_id: Optional[str] = Header(default=None, alias="X-Incident-Id")):
    """Convenience endpoint that explicitly produces a failure for testing."""
    return execute_checkout(simulate_error=True, x_incident_id=x_incident_id)

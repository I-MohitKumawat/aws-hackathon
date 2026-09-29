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
service_name = os.getenv("OTEL_SERVICE_NAME", "payment")
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
tracer = trace.get_tracer("payment.service", service_version)

app = FastAPI(
    title="Instrumented Payment Service",
    description="Microservice managing payment authorization and capture with OpenTelemetry tracing.",
    version=service_version,
)

# Instrument FastAPI automatically (handles incoming W3C traceparent extraction)
FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)

class PaymentGatewayError(Exception):
    """Simulated payment gateway rejection exception."""
    pass

class PaymentRequest(BaseModel):
    order_id: str
    amount: float = 149.99
    payment_method: str = "card"

class PaymentResponse(BaseModel):
    payment_id: str
    order_id: str
    status: str
    amount: float
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

@app.post("/payment/process", response_model=PaymentResponse)
def process_payment(
    payload: PaymentRequest,
    simulate_error: bool = Query(default=False),
    x_incident_id: Optional[str] = Header(default=None, alias="X-Incident-Id"),
):
    """
    Authorizes and captures customer payment.
    Emits child spans and supports controllable gateway rejection failures.
    """
    current_span = trace.get_current_span()
    if x_incident_id and current_span:
        current_span.set_attribute("incident.id", x_incident_id)

    payment_id = f"pay_{uuid.uuid4().hex[:8]}"

    # Span 1: Authorize Card with External Gateway
    with tracer.start_as_current_span("payment.authorize") as auth_span:
        if x_incident_id:
            auth_span.set_attribute("incident.id", x_incident_id)
        auth_span.set_attribute("payment.provider", "mock_gateway")
        auth_span.set_attribute("payment.amount", payload.amount)
        auth_span.set_attribute("payment.method", payload.payment_method)

        if simulate_error or payload.amount > 5000:
            err_msg = f"Payment gateway transaction declined: card_issuer_declined (insufficient funds / fraud check failed) for order {payload.order_id}"
            exc = PaymentGatewayError(err_msg)
            auth_span.record_exception(exc)
            auth_span.set_status(Status(StatusCode.ERROR, description=err_msg))
            auth_span.set_attribute("error.type", "GATEWAY_DECLINED")
            auth_span.set_attribute("payment.gateway.status_code", 402)

            if current_span:
                current_span.set_status(Status(StatusCode.ERROR, description=err_msg))
                current_span.set_attribute("error.type", "GATEWAY_DECLINED")

            provider.force_flush()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=err_msg,
            )

        auth_span.set_attribute("payment.authorized", True)
        auth_span.set_attribute("payment.auth_code", "AUTH_99182")
        time.sleep(0.02)

    # Span 2: Capture Funds
    with tracer.start_as_current_span("payment.capture") as capture_span:
        if x_incident_id:
            capture_span.set_attribute("incident.id", x_incident_id)
        capture_span.set_attribute("payment.payment_id", payment_id)
        capture_span.set_attribute("payment.captured", True)
        time.sleep(0.015)

    provider.force_flush()

    return PaymentResponse(
        payment_id=payment_id,
        order_id=payload.order_id,
        status="captured",
        amount=payload.amount,
        service=service_name,
        version=service_version,
    )

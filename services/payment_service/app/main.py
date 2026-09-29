import logging
import os
import time
import uuid
from typing import Optional
from fastapi import FastAPI, Header, HTTPException, Query, status
from pydantic import BaseModel

from opentelemetry import trace, metrics
from opentelemetry.trace import Status, StatusCode
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

# Initialize OpenTelemetry Resource
service_name = os.getenv("OTEL_SERVICE_NAME", "payment")
service_version = os.getenv("SERVICE_VERSION", "1.0.0")
environment = os.getenv("DEPLOYMENT_ENVIRONMENT", "production")

resource = Resource.create({
    "service.name": service_name,
    "service.version": service_version,
    "deployment.environment": environment,
})

otlp_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317")
grpc_endpoint = otlp_endpoint.replace("http://", "").replace("https://", "")
is_insecure = os.getenv("OTEL_EXPORTER_OTLP_INSECURE", "true").lower() in ("true", "1")

# Tracing Setup
provider = TracerProvider(resource=resource)
otlp_exporter = OTLPSpanExporter(endpoint=grpc_endpoint, insecure=is_insecure)
provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer("payment.service", service_version)

# Logging Setup
logger_provider = LoggerProvider(resource=resource)
log_processor = BatchLogRecordProcessor(OTLPLogExporter(endpoint=grpc_endpoint, insecure=is_insecure))
logger_provider.add_log_record_processor(log_processor)
set_logger_provider(logger_provider)

log_handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)
logging.getLogger().addHandler(log_handler)
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger("payment")

# Metrics Setup
metric_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint=grpc_endpoint, insecure=is_insecure),
    export_interval_millis=2000,
)
meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
metrics.set_meter_provider(meter_provider)
meter = metrics.get_meter("payment.service", service_version)

payment_transactions_counter = meter.create_counter(
    "payment.transactions.total",
    description="Total payment transactions processed",
    unit="1",
)
payment_declined_counter = meter.create_counter(
    "payment.gateway.declined",
    description="Total payment gateway declined transactions",
    unit="1",
)

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
    extra_tags = {"incident.id": x_incident_id, "order_id": payload.order_id} if x_incident_id else {"order_id": payload.order_id}
    metric_attrs = {"service": service_name}
    if x_incident_id:
        metric_attrs["incident.id"] = x_incident_id

    logger.info("Processing payment for order %s of amount $%.2f (method: %s)", payload.order_id, payload.amount, payload.payment_method, extra=extra_tags)

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

            logger.error("Payment gateway transaction declined: card_issuer_declined (insufficient funds / fraud check failed) for order %s", payload.order_id, extra=extra_tags, exc_info=True)
            payment_transactions_counter.add(1, {**metric_attrs, "status": "declined", "error_type": "GATEWAY_DECLINED"})
            payment_declined_counter.add(1, metric_attrs)

            provider.force_flush()
            log_processor.force_flush()
            metric_reader.force_flush()
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

    logger.info("Payment authorized and captured successfully: payment_id=%s for order %s (amount: $%.2f)", payment_id, payload.order_id, payload.amount, extra=extra_tags)
    payment_transactions_counter.add(1, {**metric_attrs, "status": "success"})

    provider.force_flush()
    log_processor.force_flush()
    metric_reader.force_flush()

    return PaymentResponse(
        payment_id=payment_id,
        order_id=payload.order_id,
        status="captured",
        amount=payload.amount,
        service=service_name,
        version=service_version,
    )

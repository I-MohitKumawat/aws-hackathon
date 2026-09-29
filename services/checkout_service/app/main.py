import os
import time
import uuid
from typing import Optional, List
import requests
from fastapi import FastAPI, Header, HTTPException, Query, status
from pydantic import BaseModel

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

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

# Downstream Service URLs
INVENTORY_SERVICE_URL = os.getenv("INVENTORY_SERVICE_URL", "http://localhost:8081").rstrip("/")
PAYMENT_SERVICE_URL = os.getenv("PAYMENT_SERVICE_URL", "http://localhost:8082").rstrip("/")

app = FastAPI(
    title="Instrumented Checkout Service",
    description="Multi-service checkout coordinator emitting OpenTelemetry traces with W3C context propagation.",
    version=service_version,
)

# Instrument FastAPI automatically for inbound HTTP request spans (extracts W3C context)
FastAPIInstrumentor.instrument_app(app, tracer_provider=provider)

class ConnectionPoolTimeoutError(Exception):
    """Simulated database connection pool exhaustion exception."""
    pass

class DownstreamServiceError(Exception):
    """Exception raised when a downstream dependency fails."""
    pass

class CheckoutRequest(BaseModel):
    items: list[str] = ["item_alpha", "item_beta", "item_gamma"]
    total: float = 149.99

class CheckoutResponse(BaseModel):
    order_id: str
    status: str
    total: float
    reservation_id: Optional[str] = None
    payment_id: Optional[str] = None
    service: str
    version: str

@app.get("/health")
def health():
    return {
        "status": "healthy",
        "service": service_name,
        "version": service_version,
        "otlp_endpoint": grpc_endpoint,
        "inventory_url": INVENTORY_SERVICE_URL,
        "payment_url": PAYMENT_SERVICE_URL,
    }

@app.post("/checkout", response_model=CheckoutResponse)
def execute_checkout(
    payload: Optional[CheckoutRequest] = None,
    simulate_error: bool = Query(default=False, description="Simulate checkout DB connection pool failure"),
    simulate_inventory_error: bool = Query(default=False, description="Simulate downstream inventory out-of-stock failure"),
    simulate_payment_error: bool = Query(default=False, description="Simulate downstream payment gateway failure"),
    x_incident_id: Optional[str] = Header(default=None, alias="X-Incident-Id"),
):
    """
    Executes an end-to-end checkout workflow across microservices:
    1. Validates cart locally (internal span)
    2. Acquires database connection locally (internal span, controllable failure)
    3. Calls Inventory Service to reserve stock (HTTP client span + W3C context propagation)
    4. Calls Payment Service to process charge (HTTP client span + W3C context propagation)
    """
    current_span = trace.get_current_span()
    if x_incident_id and current_span:
        current_span.set_attribute("incident.id", x_incident_id)

    order_id = f"ord_{uuid.uuid4().hex[:8]}"
    items = payload.items if payload else ["item_alpha", "item_beta", "item_gamma"]
    total_val = payload.total if payload else 149.99

    # Step 1: Validate Cart (Internal Span)
    with tracer.start_as_current_span("validate_cart") as span:
        if x_incident_id:
            span.set_attribute("incident.id", x_incident_id)
        span.set_attribute("cart.items_count", len(items))
        span.set_attribute("cart.total_amount", total_val)
        time.sleep(0.01)

    # Step 2: Database Connection & Operation (Internal Span, controllable failure)
    with tracer.start_as_current_span("db.acquire_connection") as db_span:
        if x_incident_id:
            db_span.set_attribute("incident.id", x_incident_id)
        db_span.set_attribute("db.system", "postgresql")
        db_span.set_attribute("db.pool.max", 20)

        if simulate_error:
            err_msg = "Connection pool timeout: unable to obtain connection to postgresql://db-primary:5432/checkout within 5000ms"
            exc = ConnectionPoolTimeoutError(err_msg)
            db_span.record_exception(exc)
            db_span.set_status(Status(StatusCode.ERROR, description=err_msg))
            db_span.set_attribute("error.type", "POOL_TIMEOUT")
            db_span.set_attribute("db.pool.active", 20)

            if current_span:
                current_span.set_status(Status(StatusCode.ERROR, description=err_msg))
                current_span.set_attribute("error.type", "POOL_TIMEOUT")

            provider.force_flush()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=err_msg,
            )

        db_span.set_attribute("db.connection.reused", True)
        time.sleep(0.01)

    # Step 3: Call Downstream Inventory Service (Outgoing HTTP with W3C Context Propagation)
    reservation_id = None
    with tracer.start_as_current_span("call_inventory_service") as inv_client_span:
        if x_incident_id:
            inv_client_span.set_attribute("incident.id", x_incident_id)
        inv_client_span.set_attribute("http.method", "POST")
        inv_client_span.set_attribute("http.url", f"{INVENTORY_SERVICE_URL}/inventory/reserve")
        inv_client_span.set_attribute("peer.service", "inventory")

        inv_headers = {"Content-Type": "application/json"}
        # Inject W3C traceparent and tracestate into outgoing headers
        TraceContextTextMapPropagator().inject(inv_headers)
        if x_incident_id:
            inv_headers["X-Incident-Id"] = x_incident_id

        try:
            inv_resp = requests.post(
                f"{INVENTORY_SERVICE_URL}/inventory/reserve",
                json={"items": items, "order_id": order_id},
                params={"simulate_error": "true" if simulate_inventory_error else "false"},
                headers=inv_headers,
                timeout=10,
            )
            inv_client_span.set_attribute("http.status_code", inv_resp.status_code)

            if inv_resp.status_code != 200:
                err_detail = inv_resp.json().get("detail", inv_resp.text)
                exc = DownstreamServiceError(f"Inventory service failed with HTTP {inv_resp.status_code}: {err_detail}")
                inv_client_span.record_exception(exc)
                inv_client_span.set_status(Status(StatusCode.ERROR, description=str(exc)))
                inv_client_span.set_attribute("error.type", "DOWNSTREAM_SERVICE_ERROR")
                inv_client_span.set_attribute("failed.service", "inventory")

                if current_span:
                    current_span.set_status(Status(StatusCode.ERROR, description=str(exc)))
                    current_span.set_attribute("error.type", "DOWNSTREAM_SERVICE_ERROR")
                    current_span.set_attribute("failed.service", "inventory")

                provider.force_flush()
                raise HTTPException(
                    status_code=inv_resp.status_code,
                    detail=f"Downstream service 'inventory' failed: {err_detail}",
                )

            inv_data = inv_resp.json()
            reservation_id = inv_data.get("reservation_id")
            inv_client_span.set_attribute("inventory.reservation_id", str(reservation_id))

        except requests.RequestException as req_exc:
            inv_client_span.record_exception(req_exc)
            inv_client_span.set_status(Status(StatusCode.ERROR, description=str(req_exc)))
            provider.force_flush()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Could not connect to inventory service: {req_exc}",
            ) from req_exc

    # Step 4: Call Downstream Payment Service (Outgoing HTTP with W3C Context Propagation)
    payment_id = None
    with tracer.start_as_current_span("call_payment_service") as pay_client_span:
        if x_incident_id:
            pay_client_span.set_attribute("incident.id", x_incident_id)
        pay_client_span.set_attribute("http.method", "POST")
        pay_client_span.set_attribute("http.url", f"{PAYMENT_SERVICE_URL}/payment/process")
        pay_client_span.set_attribute("peer.service", "payment")

        pay_headers = {"Content-Type": "application/json"}
        # Inject W3C traceparent and tracestate into outgoing headers
        TraceContextTextMapPropagator().inject(pay_headers)
        if x_incident_id:
            pay_headers["X-Incident-Id"] = x_incident_id

        try:
            pay_resp = requests.post(
                f"{PAYMENT_SERVICE_URL}/payment/process",
                json={"order_id": order_id, "amount": total_val, "payment_method": "card"},
                params={"simulate_error": "true" if simulate_payment_error else "false"},
                headers=pay_headers,
                timeout=10,
            )
            pay_client_span.set_attribute("http.status_code", pay_resp.status_code)

            if pay_resp.status_code != 200:
                err_detail = pay_resp.json().get("detail", pay_resp.text)
                exc = DownstreamServiceError(f"Payment service failed with HTTP {pay_resp.status_code}: {err_detail}")
                pay_client_span.record_exception(exc)
                pay_client_span.set_status(Status(StatusCode.ERROR, description=str(exc)))
                pay_client_span.set_attribute("error.type", "DOWNSTREAM_SERVICE_ERROR")
                pay_client_span.set_attribute("failed.service", "payment")

                if current_span:
                    current_span.set_status(Status(StatusCode.ERROR, description=str(exc)))
                    current_span.set_attribute("error.type", "DOWNSTREAM_SERVICE_ERROR")
                    current_span.set_attribute("failed.service", "payment")

                provider.force_flush()
                raise HTTPException(
                    status_code=pay_resp.status_code,
                    detail=f"Downstream service 'payment' failed: {err_detail}",
                )

            pay_data = pay_resp.json()
            payment_id = pay_data.get("payment_id")
            pay_client_span.set_attribute("payment.payment_id", str(payment_id))

        except requests.RequestException as req_exc:
            pay_client_span.record_exception(req_exc)
            pay_client_span.set_status(Status(StatusCode.ERROR, description=str(req_exc)))
            provider.force_flush()
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"Could not connect to payment service: {req_exc}",
            ) from req_exc

    # Flush spans
    provider.force_flush()

    return CheckoutResponse(
        order_id=order_id,
        status="completed",
        total=total_val,
        reservation_id=reservation_id,
        payment_id=payment_id,
        service=service_name,
        version=service_version,
    )

@app.post("/checkout/fail")
def fail_checkout(
    error_type: str = Query(default="checkout", description="Type of failure to trigger: checkout, inventory, payment"),
    x_incident_id: Optional[str] = Header(default=None, alias="X-Incident-Id"),
):
    """Convenience endpoint that triggers specific failure types across the multi-service flow."""
    return execute_checkout(
        simulate_error=(error_type == "checkout"),
        simulate_inventory_error=(error_type == "inventory"),
        simulate_payment_error=(error_type == "payment"),
        x_incident_id=x_incident_id,
    )

import logging
import os
import time
import uuid
from typing import List, Optional
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
service_name = os.getenv("OTEL_SERVICE_NAME", "inventory")
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
tracer = trace.get_tracer("inventory.service", service_version)

# Logging Setup
logger_provider = LoggerProvider(resource=resource)
log_processor = BatchLogRecordProcessor(OTLPLogExporter(endpoint=grpc_endpoint, insecure=is_insecure))
logger_provider.add_log_record_processor(log_processor)
set_logger_provider(logger_provider)

log_handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)
logging.getLogger().addHandler(log_handler)
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger("inventory")

# Metrics Setup
metric_reader = PeriodicExportingMetricReader(
    OTLPMetricExporter(endpoint=grpc_endpoint, insecure=is_insecure),
    export_interval_millis=2000,
)
meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
metrics.set_meter_provider(meter_provider)
meter = metrics.get_meter("inventory.service", service_version)

inventory_reservations_counter = meter.create_counter(
    "inventory.reservations.total",
    description="Total inventory reservation requests",
    unit="1",
)
inventory_out_of_stock_counter = meter.create_counter(
    "inventory.stock.out_of_stock",
    description="Total out-of-stock allocation failures",
    unit="1",
)

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

class ProductItem(BaseModel):
    sku: str
    name: str
    price: float
    category: str
    stock: int
    warehouse: str

CATALOG: List[ProductItem] = [
    ProductItem(sku="sku_keyboard_mech", name="Wireless Mechanical Keyboard", price=129.99, category="Peripherals", stock=45, warehouse="warehouse-east"),
    ProductItem(sku="sku_headphones_anc", name="Noise-Cancelling Headphones", price=199.99, category="Audio", stock=28, warehouse="warehouse-east"),
    ProductItem(sku="sku_monitor_4k", name="32\" 4K USB-C Monitor", price=449.99, category="Displays", stock=14, warehouse="warehouse-east"),
    ProductItem(sku="sku_desk_chair", name="Ergonomic Mesh Chair", price=299.99, category="Furniture", stock=8, warehouse="warehouse-east"),
    ProductItem(sku="sku_laptop_stand", name="Aluminum Laptop Stand", price=49.99, category="Accessories", stock=62, warehouse="warehouse-east"),
]

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

@app.get("/inventory/items", response_model=List[ProductItem])
def list_inventory_items():
    """Returns the available e-commerce product catalog with stock levels and warehouse locations."""
    return CATALOG

@app.post("/inventory/reserve", response_model=ReserveResponse)
def reserve_inventory(
    payload: ReserveRequest,
    simulate_error: bool = Query(default=False),
    latency_ms: int = Query(default=0, ge=0, le=30000, description="Inject latency delay in milliseconds"),
    x_incident_id: Optional[str] = Header(default=None, alias="X-Incident-Id"),
):
    """
    Validates item availability and reserves inventory.
    Emits child spans and supports controllable out-of-stock failures and latency injection.
    """
    if latency_ms > 0:
        time.sleep(latency_ms / 1000.0)

    current_span = trace.get_current_span()
    if x_incident_id and current_span:
        current_span.set_attribute("incident.id", x_incident_id)

    reservation_id = f"res_{uuid.uuid4().hex[:8]}"
    extra_tags = {"incident.id": x_incident_id, "order_id": payload.order_id} if x_incident_id else {"order_id": payload.order_id}
    metric_attrs = {"service": service_name}
    if x_incident_id:
        metric_attrs["incident.id"] = x_incident_id

    logger.info("Stock reservation requested for %d items (order: %s)", len(payload.items), payload.order_id, extra=extra_tags)

    # Span 1: Check Stock Availability
    with tracer.start_as_current_span("inventory.check_stock") as stock_span:
        if x_incident_id:
            stock_span.set_attribute("incident.id", x_incident_id)
        stock_span.set_attribute("inventory.items_count", len(payload.items))
        stock_span.set_attribute("inventory.warehouse", "warehouse-east")

        if simulate_error or "out_of_stock" in payload.items or any(i in ["sku_out_of_stock", "item_out_of_stock"] for i in payload.items):
            err_msg = f"Inventory allocation failed: Item 'item_beta' is out of stock in warehouse-east (requested {len(payload.items)} items)"
            exc = InventoryOutOfStockError(err_msg)
            stock_span.record_exception(exc)
            stock_span.set_status(Status(StatusCode.ERROR, description=err_msg))
            stock_span.set_attribute("error.type", "OUT_OF_STOCK")
            stock_span.set_attribute("inventory.stock_level", 0)

            if current_span:
                current_span.set_status(Status(StatusCode.ERROR, description=err_msg))
                current_span.set_attribute("error.type", "OUT_OF_STOCK")

            logger.error("Inventory allocation failed: Item 'item_beta' is out of stock in warehouse-east (requested %d items for order %s)", len(payload.items), payload.order_id, extra=extra_tags, exc_info=True)
            inventory_reservations_counter.add(1, {**metric_attrs, "status": "out_of_stock", "error_type": "OUT_OF_STOCK"})
            inventory_out_of_stock_counter.add(1, metric_attrs)

            provider.force_flush()
            log_processor.force_flush()
            metric_reader.force_flush()
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

    logger.info("Reserved %d items successfully: reservation_id=%s for order %s", len(payload.items), reservation_id, payload.order_id, extra=extra_tags)
    inventory_reservations_counter.add(1, {**metric_attrs, "status": "success"})

    provider.force_flush()
    log_processor.force_flush()
    metric_reader.force_flush()

    return ReserveResponse(
        reservation_id=reservation_id,
        status="reserved",
        items=payload.items,
        service=service_name,
        version=service_version,
    )

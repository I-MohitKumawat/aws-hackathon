from datetime import datetime, timezone
from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

from ..models import Incident, Evidence

class ScenarioCategory(str, Enum):
    ROOT_CAUSE_KNOWN = "root_cause_known"
    INCOMPLETE_EVIDENCE = "incomplete_evidence"
    AMBIGUOUS_EVIDENCE = "ambiguous_evidence"
    CONTRADICTORY_EVIDENCE = "contradictory_evidence"
    INSUFFICIENT_TELEMETRY = "insufficient_telemetry"

class ScenarioGroundTruth(BaseModel):
    primary_cause: str
    primary_cause_keywords: List[str]
    symptoms: List[str]
    symptom_keywords: List[str]
    expected_hypotheses_status: str  # "supported", "possible", "inconclusive"
    essential_evidence_ids: List[str]
    irrelevant_evidence_ids: List[str] = Field(default_factory=list)
    contradicting_evidence_ids: List[str] = Field(default_factory=list)
    expected_diagnostic_actions: List[str]
    action_keywords: List[str]
    true_cause_identifiable: bool = True
    notes: str = ""

class EvaluationScenario(BaseModel):
    id: str
    name: str
    description: str
    category: ScenarioCategory
    incident_data: Dict[str, Any]
    evidence_data: List[Dict[str, Any]]
    ground_truth: ScenarioGroundTruth

    def to_models(self) -> tuple[Incident, List[Evidence]]:
        """Instantiates in-memory SQLAlchemy Incident and Evidence models without DB persistence."""
        started_dt = datetime.fromisoformat(self.incident_data["started_at"].replace("Z", "+00:00"))
        incident = Incident(
            id=self.incident_data["id"],
            title=self.incident_data["title"],
            service=self.incident_data["service"],
            severity=self.incident_data["severity"],
            status=self.incident_data.get("status", "open"),
            description=self.incident_data.get("description", ""),
            started_at=started_dt,
            created_at=datetime.now(timezone.utc),
        )

        evidence_items = []
        for ev in self.evidence_data:
            ts_dt = datetime.fromisoformat(ev["timestamp"].replace("Z", "+00:00"))
            evidence_items.append(
                Evidence(
                    id=ev["id"],
                    incident_id=self.incident_data["id"],
                    type=ev["type"],
                    timestamp=ts_dt,
                    service=ev["service"],
                    severity=ev["severity"],
                    message=ev["message"],
                    trace_id=ev.get("trace_id"),
                    source=ev.get("source", "otel"),
                    metadata_json=ev.get("metadata", {}),
                    created_at=datetime.now(timezone.utc),
                )
            )
        return incident, evidence_items

EVALUATION_DATASET_VERSION = "1.0.0"

EVALUATION_SCENARIOS: List[EvaluationScenario] = [
    # 1. Database Connection Pool Exhaustion (Known Root Cause)
    EvaluationScenario(
        id="scen_db_pool_exhaustion",
        name="PostgreSQL Connection Pool Exhaustion",
        description="Checkout service fails with 500 when active connections hit pool max capacity of 20/20.",
        category=ScenarioCategory.ROOT_CAUSE_KNOWN,
        incident_data={
            "id": "inc_eval_db_pool",
            "title": "Checkout service HTTP 500 database pool exhaustion",
            "service": "checkout",
            "severity": "critical",
            "status": "open",
            "started_at": "2026-09-30T09:00:00Z",
            "description": "Checkout service returning HTTP 500 on all order submissions due to pool acquisition failure.",
        },
        evidence_data=[
            {
                "id": "ev_db_span_01",
                "type": "trace",
                "timestamp": "2026-09-30T09:00:05Z",
                "service": "checkout",
                "severity": "error",
                "message": "Span 'db.acquire_connection' failed: ConnectionPoolTimeoutError: connection acquisition timed out after 5000ms",
                "trace_id": "tr_eval_db_01",
                "metadata": {"span_name": "db.acquire_connection", "duration_ms": 5002},
            },
            {
                "id": "ev_db_log_01",
                "type": "log",
                "timestamp": "2026-09-30T09:00:06Z",
                "service": "checkout",
                "severity": "error",
                "message": "Connection pool timeout: unable to obtain connection to postgresql://db-primary:5432/checkout within 5000ms. Active: 20/20.",
                "trace_id": "tr_eval_db_01",
                "metadata": {"pool_size": 20, "active_connections": 20, "error": "ConnectionPoolTimeoutError"},
            },
            {
                "id": "ev_db_met_01",
                "type": "metric",
                "timestamp": "2026-09-30T09:00:10Z",
                "service": "checkout",
                "severity": "error",
                "message": "Metric 'checkout.db.pool.active_connections' reached max capacity 20.0 (limit: 20)",
                "trace_id": None,
                "metadata": {"metric": "checkout.db.pool.active_connections", "value": 20.0, "max": 20},
            },
            {
                "id": "ev_noise_chk_01",
                "type": "log",
                "timestamp": "2026-09-30T08:59:50Z",
                "service": "checkout",
                "severity": "info",
                "message": "Routine health check GET /health responded 200 in 2ms",
                "trace_id": None,
                "metadata": {"endpoint": "/health"},
            },
        ],
        ground_truth=ScenarioGroundTruth(
            primary_cause="PostgreSQL database connection pool exhaustion",
            primary_cause_keywords=["connection pool", "pool exhaustion", "pool timeout", "connections", "db connection"],
            symptoms=["HTTP 500 error", "checkout latency", "order submission failure"],
            symptom_keywords=["500", "timeout", "failed to process", "order failure"],
            expected_hypotheses_status="supported",
            essential_evidence_ids=["ev_db_span_01", "ev_db_log_01", "ev_db_met_01"],
            irrelevant_evidence_ids=["ev_noise_chk_01"],
            expected_diagnostic_actions=[
                "Check pg_stat_activity for long-running transactions and locks",
                "Inspect connection pool settings and increase max_connections if appropriate",
                "Verify database connection release logic in checkout worker",
            ],
            action_keywords=["pg_stat_activity", "pool", "max_connections", "connection", "transaction", "leak"],
            true_cause_identifiable=True,
            notes="Standard root cause scenario: traces, logs, and metrics all corroborate pool exhaustion.",
        ),
    ),

    # 2. Payment Gateway Decline / Timeout (Known Root Cause)
    EvaluationScenario(
        id="scen_payment_gateway_decline",
        name="Downstream Payment Gateway Decline",
        description="Checkout returns HTTP 502 because payment service received card_issuer_declined from processor.",
        category=ScenarioCategory.ROOT_CAUSE_KNOWN,
        incident_data={
            "id": "inc_eval_pay_decline",
            "title": "Payment gateway rejection during checkout transactions",
            "service": "checkout",
            "severity": "high",
            "status": "open",
            "started_at": "2026-09-30T09:10:00Z",
            "description": "Customers experiencing checkout failures with 502 Bad Gateway at payment step.",
        },
        evidence_data=[
            {
                "id": "ev_pay_span_chk",
                "type": "trace",
                "timestamp": "2026-09-30T09:10:02Z",
                "service": "checkout",
                "severity": "error",
                "message": "Span 'call_payment_service' failed with HTTP 502: payment service declined transaction",
                "trace_id": "tr_eval_pay_01",
                "metadata": {"downstream_service": "payment", "status_code": 502},
            },
            {
                "id": "ev_pay_span_svc",
                "type": "trace",
                "timestamp": "2026-09-30T09:10:02Z",
                "service": "payment",
                "severity": "error",
                "message": "Span 'payment.authorize' failed: card_issuer_declined",
                "trace_id": "tr_eval_pay_01",
                "metadata": {"gateway": "stripe", "decline_code": "card_issuer_declined"},
            },
            {
                "id": "ev_pay_log_01",
                "type": "log",
                "timestamp": "2026-09-30T09:10:02Z",
                "service": "payment",
                "severity": "error",
                "message": "Payment gateway transaction declined: card_issuer_declined (insufficient funds / fraud check failed) for order ord_pay_991",
                "trace_id": "tr_eval_pay_01",
                "metadata": {"decline_code": "card_issuer_declined", "order_id": "ord_pay_991"},
            },
            {
                "id": "ev_pay_noise_01",
                "type": "metric",
                "timestamp": "2026-09-30T09:09:59Z",
                "service": "payment",
                "severity": "info",
                "message": "Metric 'payment.worker.cpu' utilization normal at 12.4%",
                "trace_id": None,
                "metadata": {"cpu_utilization": 12.4},
            },
        ],
        ground_truth=ScenarioGroundTruth(
            primary_cause="Downstream payment gateway declined transaction with card_issuer_declined",
            primary_cause_keywords=["payment gateway", "card_issuer_declined", "declined", "payment service", "fraud check"],
            symptoms=["HTTP 502 Bad Gateway", "checkout failure", "payment step failure"],
            symptom_keywords=["502", "bad gateway", "checkout error"],
            expected_hypotheses_status="supported",
            essential_evidence_ids=["ev_pay_span_chk", "ev_pay_span_svc", "ev_pay_log_01"],
            irrelevant_evidence_ids=["ev_pay_noise_01"],
            expected_diagnostic_actions=[
                "Inspect payment gateway webhook and decline audit logs",
                "Verify whether customer cards are triggering fraud filters or insufficient funds",
                "Check payment service gateway connectivity and API keys",
            ],
            action_keywords=["gateway", "decline", "webhook", "fraud", "issuer", "audit"],
            true_cause_identifiable=True,
            notes="Tests downstream fault localization: checkout symptom is 502, but true cause is payment gateway decline.",
        ),
    ),

    # 3. Inventory Allocation Out of Stock (Known Root Cause)
    EvaluationScenario(
        id="scen_inventory_out_of_stock",
        name="Inventory Allocation Out of Stock",
        description="Checkout returns HTTP 409 because inventory service cannot reserve requested SKU in warehouse-east.",
        category=ScenarioCategory.ROOT_CAUSE_KNOWN,
        incident_data={
            "id": "inc_eval_inv_oos",
            "title": "Inventory reservation conflict 409 during order placement",
            "service": "checkout",
            "severity": "medium",
            "status": "open",
            "started_at": "2026-09-30T09:20:00Z",
            "description": "Order submissions failing with 409 Conflict when attempting inventory reservation.",
        },
        evidence_data=[
            {
                "id": "ev_inv_span_01",
                "type": "trace",
                "timestamp": "2026-09-30T09:20:03Z",
                "service": "inventory",
                "severity": "error",
                "message": "Span 'inventory.reserve_items' failed: InventoryOutOfStockError: Item 'sku_laptop_stand' is out of stock in warehouse-east",
                "trace_id": "tr_eval_inv_01",
                "metadata": {"sku": "sku_laptop_stand", "warehouse": "warehouse-east"},
            },
            {
                "id": "ev_inv_log_01",
                "type": "log",
                "timestamp": "2026-09-30T09:20:03Z",
                "service": "inventory",
                "severity": "error",
                "message": "Inventory allocation failed: Item 'sku_laptop_stand' is out of stock in warehouse-east (requested 2 items for order ord_inv_772)",
                "trace_id": "tr_eval_inv_01",
                "metadata": {"sku": "sku_laptop_stand", "warehouse": "warehouse-east", "requested_qty": 2},
            },
            {
                "id": "ev_inv_chk_log",
                "type": "log",
                "timestamp": "2026-09-30T09:20:04Z",
                "service": "checkout",
                "severity": "error",
                "message": "Order ord_inv_772 failed: Inventory service error: Inventory service failed with HTTP 409: Inventory allocation failed: Item 'sku_laptop_stand' is out of stock",
                "trace_id": "tr_eval_inv_01",
                "metadata": {"http_status": 409},
            },
        ],
        ground_truth=ScenarioGroundTruth(
            primary_cause="Inventory allocation failed due to out of stock condition for SKU in warehouse-east",
            primary_cause_keywords=["out of stock", "inventory allocation", "sku_laptop_stand", "warehouse-east", "inventory"],
            symptoms=["HTTP 409 Conflict", "order placement failure"],
            symptom_keywords=["409", "conflict", "failed reservation"],
            expected_hypotheses_status="supported",
            essential_evidence_ids=["ev_inv_span_01", "ev_inv_log_01", "ev_inv_chk_log"],
            irrelevant_evidence_ids=[],
            expected_diagnostic_actions=[
                "Check warehouse inventory quantities for sku_laptop_stand in warehouse-east",
                "Verify inventory replenishment pipeline and safety stock thresholds",
                "Update product catalog availability status to out-of-stock",
            ],
            action_keywords=["warehouse", "stock", "quantity", "replenishment", "sku", "catalog"],
            true_cause_identifiable=True,
            notes="Tests downstream inventory isolation and concrete stock diagnostic recommendations.",
        ),
    ),

    # 4. Elevated Error Rate Post-Deployment (Known Root Cause)
    EvaluationScenario(
        id="scen_elevated_error_rate",
        name="Post-Deployment NullPointerException Spike",
        description="Checkout error rate spikes to 18.5% immediately following deployment checkout-v2.2.0 due to serializer bug.",
        category=ScenarioCategory.ROOT_CAUSE_KNOWN,
        incident_data={
            "id": "inc_eval_elevated_err",
            "title": "Elevated 5xx error rate post-deployment checkout-v2.2.0",
            "service": "checkout",
            "severity": "critical",
            "status": "open",
            "started_at": "2026-09-30T09:30:00Z",
            "description": "5xx error rate spiked immediately following deployment checkout-v2.2.0.",
        },
        evidence_data=[
            {
                "id": "ev_dep_event_01",
                "type": "deployment",
                "timestamp": "2026-09-30T09:28:00Z",
                "service": "checkout",
                "severity": "info",
                "message": "Deployment checkout-v2.2.0 completed by CI/CD pipeline",
                "trace_id": None,
                "metadata": {"version": "v2.2.0", "commit": "c4d5e6f"},
            },
            {
                "id": "ev_ser_log_01",
                "type": "log",
                "timestamp": "2026-09-30T09:30:05Z",
                "service": "checkout",
                "severity": "error",
                "message": "Unhandled NullPointerException in CartItemsSerializer.serialize(): order.discounts is null",
                "trace_id": "tr_eval_err_01",
                "metadata": {"exception": "NullPointerException", "class": "CartItemsSerializer"},
            },
            {
                "id": "ev_rate_met_01",
                "type": "metric",
                "timestamp": "2026-09-30T09:30:30Z",
                "service": "checkout",
                "severity": "error",
                "message": "Metric 'http_requests_5xx_rate' spiked to 18.5% (normal baseline: <0.5%)",
                "trace_id": None,
                "metadata": {"metric": "http_requests_5xx_rate", "value": 18.5, "threshold": 0.5},
            },
        ],
        ground_truth=ScenarioGroundTruth(
            primary_cause="Deployment checkout-v2.2.0 introduced a NullPointerException in CartItemsSerializer",
            primary_cause_keywords=["v2.2.0", "deployment", "nullpointerexception", "cartitemsserializer", "discounts"],
            symptoms=["HTTP 5xx error rate spike to 18.5%", "unhandled exception in checkout"],
            symptom_keywords=["5xx", "error rate", "spike", "unhandled"],
            expected_hypotheses_status="supported",
            essential_evidence_ids=["ev_dep_event_01", "ev_ser_log_01", "ev_rate_met_01"],
            irrelevant_evidence_ids=[],
            expected_diagnostic_actions=[
                "Roll back deployment checkout-v2.2.0 to the previous stable release",
                "Add null safety guard for order.discounts in CartItemsSerializer",
                "Review diff for commit c4d5e6f in CI/CD repository",
            ],
            action_keywords=["rollback", "revert", "diff", "null", "v2.2.0", "commit"],
            true_cause_identifiable=True,
            notes="Tests correlation of deployment event with code exception and metric spike.",
        ),
    ),

    # 5. Sustained Latency Spike (Known Root Cause)
    EvaluationScenario(
        id="scen_sustained_latency_spike",
        name="Unindexed Sequential Scan Latency Spike",
        description="Inventory service latency spikes to 4500ms due to sequential scan on inventory_items table.",
        category=ScenarioCategory.ROOT_CAUSE_KNOWN,
        incident_data={
            "id": "inc_eval_lat_spike",
            "title": "Sustained inventory service latency spike (>4000ms)",
            "service": "inventory",
            "severity": "high",
            "status": "open",
            "started_at": "2026-09-30T09:40:00Z",
            "description": "Inventory query latency degraded from 15ms to 4500ms, causing checkout timeouts.",
        },
        evidence_data=[
            {
                "id": "ev_lat_span_01",
                "type": "trace",
                "timestamp": "2026-09-30T09:40:10Z",
                "service": "inventory",
                "severity": "error",
                "message": "Span 'inventory.check_stock' duration exceeded threshold: 4520ms (threshold: 500ms)",
                "trace_id": "tr_eval_lat_01",
                "metadata": {"duration_ms": 4520, "span_name": "inventory.check_stock"},
            },
            {
                "id": "ev_lat_log_01",
                "type": "log",
                "timestamp": "2026-09-30T09:40:11Z",
                "service": "inventory",
                "severity": "warn",
                "message": "PostgreSQL slow query log: Seq Scan on inventory_items (cost=0.00..89201.00 rows=152000 width=128) duration=4490ms",
                "trace_id": "tr_eval_lat_01",
                "metadata": {"query_type": "Seq Scan", "table": "inventory_items", "duration_ms": 4490},
            },
            {
                "id": "ev_lat_met_01",
                "type": "metric",
                "timestamp": "2026-09-30T09:40:30Z",
                "service": "inventory",
                "severity": "error",
                "message": "Metric 'inventory.request.duration_ms' p99 reached 4550.0ms (threshold: 2000.0ms)",
                "trace_id": None,
                "metadata": {"metric": "inventory.request.duration_ms", "p99": 4550.0},
            },
        ],
        ground_truth=ScenarioGroundTruth(
            primary_cause="Unindexed database sequential scan on inventory_items table causing high query execution time",
            primary_cause_keywords=["seq scan", "sequential scan", "inventory_items", "slow query", "unindexed", "missing index"],
            symptoms=["Sustained latency spike", "4500ms request duration", "p99 threshold breach"],
            symptom_keywords=["latency", "duration", "4500ms", "timeout", "slow"],
            expected_hypotheses_status="supported",
            essential_evidence_ids=["ev_lat_span_01", "ev_lat_log_01", "ev_lat_met_01"],
            irrelevant_evidence_ids=[],
            expected_diagnostic_actions=[
                "Run EXPLAIN ANALYZE on query selecting from inventory_items",
                "Create missing index on inventory_items(sku, warehouse_id)",
                "Inspect database query plan and table statistics",
            ],
            action_keywords=["explain", "analyze", "index", "inventory_items", "query plan", "statistics"],
            true_cause_identifiable=True,
            notes="Tests slow query log synthesis and recommended database indexing actions.",
        ),
    ),

    # 6. Incomplete Evidence (Missing Downstream Signals)
    EvaluationScenario(
        id="scen_incomplete_evidence",
        name="Dropped Downstream Telemetry (Incomplete Evidence)",
        description="Checkout returns 500 but downstream traces and logs were dropped by collector; cause cannot be conclusively proven.",
        category=ScenarioCategory.INCOMPLETE_EVIDENCE,
        incident_data={
            "id": "inc_eval_incomplete",
            "title": "Checkout failure with missing downstream telemetry",
            "service": "checkout",
            "severity": "high",
            "status": "open",
            "started_at": "2026-09-30T09:50:00Z",
            "description": "Checkout failed during downstream RPC orchestration, but downstream logs and traces are absent.",
        },
        evidence_data=[
            {
                "id": "ev_inc_span_01",
                "type": "trace",
                "timestamp": "2026-09-30T09:50:05Z",
                "service": "checkout",
                "severity": "error",
                "message": "Span 'POST /checkout' failed: DownstreamServiceError: Downstream call failed with unhandled remote error",
                "trace_id": "tr_eval_inc_01",
                "metadata": {"http_status": 500, "span_name": "POST /checkout"},
            },
            {
                "id": "ev_inc_log_01",
                "type": "log",
                "timestamp": "2026-09-30T09:50:05Z",
                "service": "checkout",
                "severity": "error",
                "message": "Checkout orchestration failed for order ord_inc_123: remote service did not return valid response body",
                "trace_id": "tr_eval_inc_01",
                "metadata": {"order_id": "ord_inc_123"},
            },
        ],
        ground_truth=ScenarioGroundTruth(
            primary_cause="Downstream service failure, but specific root cause is unidentifiable due to missing downstream logs and traces",
            primary_cause_keywords=["downstream", "missing", "incomplete", "unidentifiable", "insufficient"],
            symptoms=["Checkout 500 error", "DownstreamServiceError", "remote response failure"],
            symptom_keywords=["500", "downstream error", "orchestration failed"],
            expected_hypotheses_status="inconclusive",  # Must NOT be "supported"
            essential_evidence_ids=["ev_inc_span_01", "ev_inc_log_01"],
            irrelevant_evidence_ids=[],
            expected_diagnostic_actions=[
                "Check downstream service logs for Inventory and Payment microservices",
                "Verify OpenTelemetry collector exporter health to ensure downstream telemetry is ingested",
                "Inspect network connectivity and ingress timeouts between checkout and downstream services",
            ],
            action_keywords=["downstream", "collector", "payment", "inventory", "telemetry", "ingestion", "logs"],
            true_cause_identifiable=False,
            notes="AI must recognize that telemetry is incomplete, state missing evidence, and avoid claiming supported root cause.",
        ),
    ),

    # 7. Ambiguous Evidence (Multiple Concurrent Anomalies)
    EvaluationScenario(
        id="scen_ambiguous_evidence",
        name="Concurrent Database CPU Spike & Third-Party API Timeout",
        description="Checkout experiences failures while database CPU hits 95% AND third-party fixer.io currency API returns 504.",
        category=ScenarioCategory.AMBIGUOUS_EVIDENCE,
        incident_data={
            "id": "inc_eval_ambiguous",
            "title": "Intermittent checkout timeouts during concurrent infrastructure anomalies",
            "service": "checkout",
            "severity": "high",
            "status": "open",
            "started_at": "2026-09-30T10:00:00Z",
            "description": "Checkout transactions failing while both database host CPU and external currency API show severe degradation.",
        },
        evidence_data=[
            {
                "id": "ev_amb_db_cpu",
                "type": "metric",
                "timestamp": "2026-09-30T10:00:10Z",
                "service": "checkout",
                "severity": "warn",
                "message": "Database host CPU utilization spiked to 95.2% on db-primary",
                "trace_id": None,
                "metadata": {"host": "db-primary", "cpu_percent": 95.2},
            },
            {
                "id": "ev_amb_api_log",
                "type": "log",
                "timestamp": "2026-09-30T10:00:12Z",
                "service": "checkout",
                "severity": "error",
                "message": "External currency service call to https://api.fixer.io/latest timed out after 3000ms (504 Gateway Timeout)",
                "trace_id": "tr_eval_amb_01",
                "metadata": {"endpoint": "https://api.fixer.io/latest", "timeout_ms": 3000, "status": 504},
            },
            {
                "id": "ev_amb_chk_span",
                "type": "trace",
                "timestamp": "2026-09-30T10:00:13Z",
                "service": "checkout",
                "severity": "error",
                "message": "Span 'POST /checkout' failed: RequestTimeoutError after 5000ms total elapsed time",
                "trace_id": "tr_eval_amb_01",
                "metadata": {"duration_ms": 5005},
            },
        ],
        ground_truth=ScenarioGroundTruth(
            primary_cause="Ambiguous concurrent bottlenecks: database high CPU utilization and third-party currency API timeout",
            primary_cause_keywords=["ambiguous", "database cpu", "currency", "api.fixer.io", "timeout", "bottleneck"],
            symptoms=["RequestTimeoutError", "checkout 500/504 timeout", "high total elapsed time"],
            symptom_keywords=["timeout", "504", "elapsed time", "5000ms"],
            expected_hypotheses_status="possible",  # Should present multiple hypotheses with possible status
            essential_evidence_ids=["ev_amb_db_cpu", "ev_amb_api_log", "ev_amb_chk_span"],
            irrelevant_evidence_ids=[],
            expected_diagnostic_actions=[
                "Correlate request span timelines to determine if database wait or currency API wait dominated elapsed time",
                "Inspect pg_stat_activity to find queries causing 95% CPU on db-primary",
                "Check external status page for api.fixer.io and configure circuit breaker or cache fallback",
            ],
            action_keywords=["timeline", "pg_stat_activity", "fixer.io", "circuit breaker", "cpu", "correlate", "cache"],
            true_cause_identifiable=False,
            notes="AI should represent both competing possibilities with 'possible' or 'inconclusive', not jump to a single absolute cause.",
        ),
    ),

    # 8. Contradictory Evidence (Engineer Note Contradicted by Metric)
    EvaluationScenario(
        id="scen_contradictory_evidence",
        name="Contradicted Deadlock Theory vs API Gateway Rate Limiting",
        description="Initial log hypothesizes database deadlock, but database metrics show 0 deadlocks while gateway logs show 429 rate limiting.",
        category=ScenarioCategory.CONTRADICTORY_EVIDENCE,
        incident_data={
            "id": "inc_eval_contradictory",
            "title": "Checkout 503 outage: reported deadlock vs gateway rate limiting",
            "service": "checkout",
            "severity": "critical",
            "status": "open",
            "started_at": "2026-09-30T10:10:00Z",
            "description": "Engineering alert indicated suspected database deadlocks, but telemetry shows upstream gateway rate limits.",
        },
        evidence_data=[
            {
                "id": "ev_contra_note_01",
                "type": "log",
                "timestamp": "2026-09-30T10:10:02Z",
                "service": "checkout",
                "severity": "warn",
                "message": "Operator note: suspected database deadlock in order checkout worker during flash sale",
                "trace_id": None,
                "metadata": {"source": "operator_annotation"},
            },
            {
                "id": "ev_contra_met_deadlocks",
                "type": "metric",
                "timestamp": "2026-09-30T10:10:05Z",
                "service": "checkout",
                "severity": "info",
                "message": "Metric 'pg_stat_database_deadlocks' count is 0 (normal baseline: 0)",
                "trace_id": None,
                "metadata": {"metric": "pg_stat_database_deadlocks", "deadlocks": 0},
            },
            {
                "id": "ev_contra_met_active_conn",
                "type": "metric",
                "timestamp": "2026-09-30T10:10:06Z",
                "service": "checkout",
                "severity": "info",
                "message": "Metric 'checkout.db.pool.active_connections' is 4/100 (healthy pool utilization)",
                "trace_id": None,
                "metadata": {"active_connections": 4, "max": 100},
            },
            {
                "id": "ev_contra_gw_log",
                "type": "log",
                "timestamp": "2026-09-30T10:10:08Z",
                "service": "checkout",
                "severity": "error",
                "message": "API Gateway rejected requests: HTTP 429 Too Many Requests (token bucket rate limit exceeded: 500 req/sec limit)",
                "trace_id": "tr_eval_contra_01",
                "metadata": {"status_code": 429, "rate_limit_exceeded": True},
            },
            {
                "id": "ev_contra_gw_span",
                "type": "trace",
                "timestamp": "2026-09-30T10:10:09Z",
                "service": "checkout",
                "severity": "error",
                "message": "Span 'ingress.api_gateway' status ERROR: 429 Too Many Requests throttled by token bucket",
                "trace_id": "tr_eval_contra_01",
                "metadata": {"span_name": "ingress.api_gateway", "http_status": 429},
            },
        ],
        ground_truth=ScenarioGroundTruth(
            primary_cause="API Gateway token bucket rate limit exceeded (HTTP 429/503), not database deadlocks",
            primary_cause_keywords=["rate limit", "token bucket", "429", "gateway", "throttled", "too many requests"],
            symptoms=["HTTP 429 Too Many Requests", "request rejection during flash sale"],
            symptom_keywords=["429", "throttled", "rejected", "flash sale"],
            expected_hypotheses_status="supported",
            essential_evidence_ids=["ev_contra_gw_log", "ev_contra_gw_span"],
            contradicting_evidence_ids=["ev_contra_met_deadlocks", "ev_contra_met_active_conn"],
            irrelevant_evidence_ids=[],
            expected_diagnostic_actions=[
                "Inspect API gateway rate limit quotas and token bucket burst settings",
                "Review ingress traffic volume from client IP addresses during flash sale",
                "Confirm database deadlock count remains zero in pg_stat_database",
            ],
            action_keywords=["rate limit", "quota", "token bucket", "burst", "gateway", "ingress", "traffic"],
            true_cause_identifiable=True,
            notes="AI must identify that the suspected deadlock is contradicted by zero deadlocks metric, and ground on rate limiting.",
        ),
    ),

    # 9. Insufficient Telemetry (Crash with Zero Telemetry)
    EvaluationScenario(
        id="scen_insufficient_telemetry",
        name="Abrupt Process Crash (Insufficient Telemetry)",
        description="Payment service abruptly terminates (OOMKilled); telemetry only shows connection reset with zero application logs.",
        category=ScenarioCategory.INSUFFICIENT_TELEMETRY,
        incident_data={
            "id": "inc_eval_insufficient",
            "title": "Payment service abrupt termination with connection reset",
            "service": "payment",
            "severity": "critical",
            "status": "open",
            "started_at": "2026-09-30T10:20:00Z",
            "description": "Payment service disconnected abruptly during active traffic; no application stack traces available.",
        },
        evidence_data=[
            {
                "id": "ev_insuf_log_01",
                "type": "log",
                "timestamp": "2026-09-30T10:20:02Z",
                "service": "checkout",
                "severity": "error",
                "message": "Connection reset by peer while reading response headers from payment-service:8082",
                "trace_id": "tr_eval_insuf_01",
                "metadata": {"downstream_host": "payment-service:8082", "errno": 104},
            },
            {
                "id": "ev_insuf_span_01",
                "type": "trace",
                "timestamp": "2026-09-30T10:20:02Z",
                "service": "checkout",
                "severity": "error",
                "message": "Span 'call_payment_service' failed: ConnectionResetError(104, 'Connection reset by peer')",
                "trace_id": "tr_eval_insuf_01",
                "metadata": {"duration_ms": 12},
            },
        ],
        ground_truth=ScenarioGroundTruth(
            primary_cause="Unknown process termination (connection reset by peer); true cause unidentifiable from available telemetry",
            primary_cause_keywords=["connection reset", "unknown", "unidentifiable", "insufficient telemetry", "abrupt termination"],
            symptoms=["Connection reset by peer", "call_payment_service failed"],
            symptom_keywords=["connection reset", "reset by peer", "failed", "104"],
            expected_hypotheses_status="inconclusive",  # STRICTLY inconclusive!
            essential_evidence_ids=["ev_insuf_log_01", "ev_insuf_span_01"],
            irrelevant_evidence_ids=[],
            expected_diagnostic_actions=[
                "Check host dmesg and syslog for kernel OOMKilled events on payment service container",
                "Inspect container restart logs with docker/podman inspect and cgroup memory limits",
                "Examine application crash core dumps or fatal exit codes",
            ],
            action_keywords=["dmesg", "oomkilled", "kernel", "container", "restart", "exit code", "cgroup", "memory limit"],
            true_cause_identifiable=False,
            notes="CRITICAL: The true cause CANNOT be known from application telemetry. AI MUST set status='inconclusive' and request host/kernel logs. Any confident software hypothesis must be penalized as an unsupported hallucination.",
        ),
    ),
]

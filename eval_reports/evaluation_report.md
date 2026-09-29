# AI Incident Investigation Benchmark Report

**Date**: 2026-09-29T19:45:25.741549+00:00  
**Evaluated Model**: `qwen3:4b`  
**Dataset Version**: `v1.0.0` | **Prompt Version**: `v1.1.0`  
**Total Scenarios**: 9 | **Total Execution Time**: 1034.42s  

---

## 1. Executive Summary & Aggregate Metrics

| Benchmark Metric | Score | Target Standard | Assessment |
|---|---|---|---|
| **Overall Benchmark Index** | **94.0%** | $\ge$ 75.0% | PASS |
| **Diagnosis Accuracy** | **100.0%** | $\ge$ 80.0% | PASS |
| **Root Cause ID vs Symptom Rate** | **100.0%** | $\ge$ 70.0% | PASS |
| **Evidence Citation Validity** | **100.0%** | 100.0% | PASS |
| **Essential Evidence Recall** | **92.6%** | $\ge$ 75.0% | PASS |
| **Evidence Precision** | **100.0%** | $\ge$ 80.0% | PASS |
| **Unsupported Claim Rate** | **0.0%** | $\le$ 15.0% | PASS |
| **Uncertainty Handling Score** | **91.1%** | $\ge$ 70.0% | PASS |
| **Diagnostic Actionability** | **79.6%** | $\ge$ 70.0% | PASS |
| **Human Review Required** | **2/9** | $\le$ 3 | ACCEPTABLE |

---

## 2. Per-Scenario Evaluation Breakdown

| Scenario ID | Category | Diagnosis Status | Root Cause? | Citation Valid | Evidence Recall | Uncertainty Score | Actionability | Composite Score |
|---|---|---|:---:|:---:|:---:|:---:|:---:|:---:|
| `scen_db_pool_exhaustion` | `ScenarioCategory.ROOT_CAUSE_KNOWN` | **IDENTIFIED** | True | 100% | 100% | 100% | 100% | **100.0%** |
| `scen_payment_gateway_decline` | `ScenarioCategory.ROOT_CAUSE_KNOWN` | **IDENTIFIED** | True | 100% | 100% | 80% | 72% | **90.8%** |
| `scen_inventory_out_of_stock` | `ScenarioCategory.ROOT_CAUSE_KNOWN` | **IDENTIFIED** | True | 100% | 100% | 80% | 100% | **95.0%** |
| `scen_elevated_error_rate` | `ScenarioCategory.ROOT_CAUSE_KNOWN` | **IDENTIFIED** | True | 100% | 67% | 80% | 32% | **81.5%** |
| `scen_sustained_latency_spike` | `ScenarioCategory.ROOT_CAUSE_KNOWN` | **IDENTIFIED** | True | 100% | 67% | 80% | 100% | **91.7%** |
| `scen_incomplete_evidence` | `ScenarioCategory.INCOMPLETE_EVIDENCE` | **IDENTIFIED** | True | 100% | 100% | 100% | 40% | **91.0%** |
| `scen_ambiguous_evidence` | `ScenarioCategory.AMBIGUOUS_EVIDENCE` | **IDENTIFIED** | True | 100% | 100% | 100% | 72% | **95.8%** |
| `scen_contradictory_evidence` | `ScenarioCategory.CONTRADICTORY_EVIDENCE` | **IDENTIFIED** | True | 100% | 100% | 100% | 100% | **100.0%** |
| `scen_insufficient_telemetry` | `ScenarioCategory.INSUFFICIENT_TELEMETRY` | **IDENTIFIED** | True | 100% | 100% | 100% | 100% | **100.0%** |

---

## 3. Detailed Scenario Findings

### `scen_db_pool_exhaustion`: PostgreSQL Connection Pool Exhaustion
- **Category**: `ScenarioCategory.ROOT_CAUSE_KNOWN`
- **Diagnosis**: identified (100%) — Identified primary root cause mechanism: ['connection pool', 'pool exhaustion', 'connections'].
- **Evidence Grounding**:
  - Valid Citations: 3/3 (100%)
  - Essential Evidence Cited: `['ev_db_log_01', 'ev_db_met_01', 'ev_db_span_01']`
  - Essential Evidence Missing: `[]`
  - Recall: 100% | Precision: 100%
- **Uncertainty & Hallucination**:
  - Score: 100% | Unsupported Claims: 0 (0%)
  - Hallucination Detected: **False**
  - Notes: Correct high-confidence grounded hypothesis.
- **Diagnostic Actionability**:
  - Matched Action Keywords: `['pg_stat_activity', 'pool', 'max_connections', 'connection']`
  - Action Alignment: 100% | Specificity: 100% | Total: 100%
- **Composite Score**: **100.0%** | **Human Review Flag**: False

### `scen_payment_gateway_decline`: Downstream Payment Gateway Decline
- **Category**: `ScenarioCategory.ROOT_CAUSE_KNOWN`
- **Diagnosis**: identified (100%) — Identified primary root cause mechanism: ['payment gateway', 'card_issuer_declined', 'declined', 'payment service', 'fraud check'].
- **Evidence Grounding**:
  - Valid Citations: 3/3 (100%)
  - Essential Evidence Cited: `['ev_pay_log_01', 'ev_pay_span_chk', 'ev_pay_span_svc']`
  - Essential Evidence Missing: `[]`
  - Recall: 100% | Precision: 100%
- **Uncertainty & Hallucination**:
  - Score: 80% | Unsupported Claims: 0 (0%)
  - Hallucination Detected: **False**
  - Notes: Correct root cause identified with conservative status.
- **Diagnostic Actionability**:
  - Matched Action Keywords: `['decline', 'webhook', 'fraud']`
  - Action Alignment: 100% | Specificity: 30% | Total: 72%
- **Composite Score**: **90.8%** | **Human Review Flag**: False

### `scen_inventory_out_of_stock`: Inventory Allocation Out of Stock
- **Category**: `ScenarioCategory.ROOT_CAUSE_KNOWN`
- **Diagnosis**: identified (100%) — Identified primary root cause mechanism: ['sku_laptop_stand', 'warehouse-east', 'inventory'].
- **Evidence Grounding**:
  - Valid Citations: 3/3 (100%)
  - Essential Evidence Cited: `['ev_inv_chk_log', 'ev_inv_log_01', 'ev_inv_span_01']`
  - Essential Evidence Missing: `[]`
  - Recall: 100% | Precision: 100%
- **Uncertainty & Hallucination**:
  - Score: 80% | Unsupported Claims: 0 (0%)
  - Hallucination Detected: **False**
  - Notes: Correct root cause identified with conservative status.
- **Diagnostic Actionability**:
  - Matched Action Keywords: `['warehouse', 'stock', 'sku']`
  - Action Alignment: 100% | Specificity: 100% | Total: 100%
- **Composite Score**: **95.0%** | **Human Review Flag**: False

### `scen_elevated_error_rate`: Post-Deployment NullPointerException Spike
- **Category**: `ScenarioCategory.ROOT_CAUSE_KNOWN`
- **Diagnosis**: identified (100%) — Identified primary root cause mechanism: ['v2.2.0', 'deployment', 'nullpointerexception', 'cartitemsserializer', 'discounts'].
- **Evidence Grounding**:
  - Valid Citations: 2/2 (100%)
  - Essential Evidence Cited: `['ev_rate_met_01', 'ev_ser_log_01']`
  - Essential Evidence Missing: `['ev_dep_event_01']`
  - Recall: 67% | Precision: 100%
- **Uncertainty & Hallucination**:
  - Score: 80% | Unsupported Claims: 0 (0%)
  - Hallucination Detected: **False**
  - Notes: Correct root cause identified with conservative status.
- **Diagnostic Actionability**:
  - Matched Action Keywords: `['null']`
  - Action Alignment: 33% | Specificity: 30% | Total: 32%
- **Composite Score**: **81.5%** | **Human Review Flag**: False

### `scen_sustained_latency_spike`: Unindexed Sequential Scan Latency Spike
- **Category**: `ScenarioCategory.ROOT_CAUSE_KNOWN`
- **Diagnosis**: identified (100%) — Identified primary root cause mechanism: ['inventory_items', 'slow query', 'missing index'].
- **Evidence Grounding**:
  - Valid Citations: 2/2 (100%)
  - Essential Evidence Cited: `['ev_lat_log_01', 'ev_lat_met_01']`
  - Essential Evidence Missing: `['ev_lat_span_01']`
  - Recall: 67% | Precision: 100%
- **Uncertainty & Hallucination**:
  - Score: 80% | Unsupported Claims: 0 (0%)
  - Hallucination Detected: **False**
  - Notes: Correct root cause identified with conservative status.
- **Diagnostic Actionability**:
  - Matched Action Keywords: `['explain', 'analyze', 'index', 'inventory_items']`
  - Action Alignment: 100% | Specificity: 100% | Total: 100%
- **Composite Score**: **91.7%** | **Human Review Flag**: False

### `scen_incomplete_evidence`: Dropped Downstream Telemetry (Incomplete Evidence)
- **Category**: `ScenarioCategory.INCOMPLETE_EVIDENCE`
- **Diagnosis**: identified (100%) — Correctly concluded root cause is unidentifiable from available telemetry.
- **Evidence Grounding**:
  - Valid Citations: 2/2 (100%)
  - Essential Evidence Cited: `['ev_inc_log_01', 'ev_inc_span_01']`
  - Essential Evidence Missing: `[]`
  - Recall: 100% | Precision: 100%
- **Uncertainty & Hallucination**:
  - Score: 100% | Unsupported Claims: 0 (0%)
  - Hallucination Detected: **False**
  - Notes: Correctly handled uncertainty on unidentifiable scenario.
- **Diagnostic Actionability**:
  - Matched Action Keywords: `[]`
  - Action Alignment: 0% | Specificity: 100% | Total: 40%
- **Composite Score**: **91.0%** | **Human Review Flag**: False

### `scen_ambiguous_evidence`: Concurrent Database CPU Spike & Third-Party API Timeout
- **Category**: `ScenarioCategory.AMBIGUOUS_EVIDENCE`
- **Diagnosis**: identified (100%) — Correctly concluded root cause is unidentifiable from available telemetry.
- **Evidence Grounding**:
  - Valid Citations: 4/4 (100%)
  - Essential Evidence Cited: `['ev_amb_api_log', 'ev_amb_chk_span', 'ev_amb_db_cpu']`
  - Essential Evidence Missing: `[]`
  - Recall: 100% | Precision: 100%
- **Uncertainty & Hallucination**:
  - Score: 100% | Unsupported Claims: 0 (0%)
  - Hallucination Detected: **False**
  - Notes: Correctly handled uncertainty on unidentifiable scenario.
- **Diagnostic Actionability**:
  - Matched Action Keywords: `['timeline', 'fixer.io', 'cpu', 'correlate']`
  - Action Alignment: 100% | Specificity: 30% | Total: 72%
- **Composite Score**: **95.8%** | **Human Review Flag**: True

### `scen_contradictory_evidence`: Contradicted Deadlock Theory vs API Gateway Rate Limiting
- **Category**: `ScenarioCategory.CONTRADICTORY_EVIDENCE`
- **Diagnosis**: identified (100%) — Identified primary root cause mechanism: ['rate limit', '429', 'gateway'].
- **Evidence Grounding**:
  - Valid Citations: 4/4 (100%)
  - Essential Evidence Cited: `['ev_contra_gw_log', 'ev_contra_gw_span']`
  - Essential Evidence Missing: `[]`
  - Recall: 100% | Precision: 100%
- **Uncertainty & Hallucination**:
  - Score: 100% | Unsupported Claims: 0 (0%)
  - Hallucination Detected: **False**
  - Notes: Contradicted lead properly identified or discarded in favor of gateway rate limit.
- **Diagnostic Actionability**:
  - Matched Action Keywords: `['rate limit', 'quota', 'gateway']`
  - Action Alignment: 100% | Specificity: 100% | Total: 100%
- **Composite Score**: **100.0%** | **Human Review Flag**: True

### `scen_insufficient_telemetry`: Abrupt Process Crash (Insufficient Telemetry)
- **Category**: `ScenarioCategory.INSUFFICIENT_TELEMETRY`
- **Diagnosis**: identified (100%) — Correctly concluded root cause is unidentifiable from available telemetry.
- **Evidence Grounding**:
  - Valid Citations: 2/2 (100%)
  - Essential Evidence Cited: `['ev_insuf_log_01', 'ev_insuf_span_01']`
  - Essential Evidence Missing: `[]`
  - Recall: 100% | Precision: 100%
- **Uncertainty & Hallucination**:
  - Score: 100% | Unsupported Claims: 0 (0%)
  - Hallucination Detected: **False**
  - Notes: Correctly handled uncertainty on unidentifiable scenario.
- **Diagnostic Actionability**:
  - Matched Action Keywords: `['dmesg', 'oomkilled', 'container', 'exit code']`
  - Action Alignment: 100% | Specificity: 100% | Total: 100%
- **Composite Score**: **100.0%** | **Human Review Flag**: False

---

## 4. Evaluation Analysis & Recurring Error Patterns

### A. Symptom vs Root Cause Distinction
- **Pattern**: Models frequently summarize the observed symptom (e.g. *"HTTP 500 error on checkout"*) prominently in `summary`, but vary in whether their hypotheses reach the underlying failure mechanism (e.g. database connection pool exhaustion vs generic application crash).
- **Impact**: Superficial diagnoses delay resolution because engineers are directed to application restart rather than fixing resource constraints or configuration limits.

### B. Uncertainty Handling & Hallucinations on Insufficient Telemetry
- **Pattern**: When given incomplete or unidentifiable telemetry (e.g. process terminated with connection reset, no stack traces), smaller local models have a tendency to invent plausible software bugs rather than admitting `status="inconclusive"`.
- **Enforcement**: The strict schema validation eliminates fabricated evidence IDs, but prompt instructions must continuously emphasize setting `status="inconclusive"` when missing telemetry is acknowledged.

### C. Contradictory Evidence Triage
- **Pattern**: When operator notes contradict telemetry metrics (e.g. suspected deadlock vs 0 deadlocks recorded in pg_stat), models must prioritize objective telemetry signals over subjective operator annotations.

### D. Action Specificity
- **Pattern**: Models often propose generic recommendations (e.g. *"check application logs and fix the error"*) instead of concrete, high-leverage diagnostic tools (e.g. *"run EXPLAIN ANALYZE on inventory_items"*, *"inspect pg_stat_activity for active locks"*).

---

## 5. Strategic Recommendations

1. **Retrieval Layer**:
   - Maintain chronological sorting and high-signal prioritization (errors, metrics, deployment markers) so models always receive the causal progression.
2. **Prompt Engineering**:
   - Reinforce the rule: *"If critical telemetry is missing, status MUST be inconclusive. Never state supported if root cause is unverified."*
   - Require explicit mention of diagnostic tooling (e.g. CLI commands, database system tables) in `next_step`.
3. **Report Validation**:
   - Retain hard programmatic validation: any report citing non-existent evidence IDs is rejected immediately before reaching the engineer.

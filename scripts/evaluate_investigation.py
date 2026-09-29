#!/usr/bin/env python3
"""
Step 9: AI Investigation Evaluation Benchmark Runner

Runs the evaluation harness across controlled incident scenarios, measuring:
1. Diagnosis Accuracy (Root Cause vs Symptom distinction)
2. Evidence Grounding (Citation validity and essential recall)
3. Uncertainty & Hallucination Handling (Inconclusive status on missing telemetry)
4. Diagnostic Actionability (Alignment and specificity of recommended next steps)

Produces:
- Structured evaluation results: <output_dir>/evaluation_results.json
- Formatted Markdown benchmark report: <output_dir>/evaluation_report.md
"""

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock

from backend.app.agent import OllamaClient
from backend.app.config import settings
from backend.app.evaluation import (
    EvaluationRunner,
    EVALUATION_SCENARIOS,
    EVALUATION_DATASET_VERSION,
    PROMPT_VERSION,
)

def create_mock_client():
    """Builds a mock client providing deterministic grounded responses for each scenario."""
    mock = AsyncMock(spec=OllamaClient)

    async def mock_generate(prompt: str, **kwargs):
        # Inspect prompt to route to the appropriate scenario mock response
        if "inc_eval_db_pool" in prompt:
            return json.dumps({
                "summary": "Checkout service failed with HTTP 500 errors due to PostgreSQL connection pool exhaustion (20/20 active connections).",
                "hypotheses": [
                    {
                        "id": "hyp_db_01",
                        "description": "Database connection pool exhausted when active connections reached max capacity of 20, causing connection acquisition timeouts.",
                        "status": "supported",
                        "supporting_evidence": ["ev_db_span_01", "ev_db_log_01", "ev_db_met_01"],
                        "contradicting_evidence": [],
                        "missing_evidence": ["pg_stat_activity long running queries"],
                        "next_step": "Inspect pg_stat_activity for long-running transactions and verify connection release in checkout worker.",
                    }
                ]
            })
        elif "inc_eval_pay_decline" in prompt:
            return json.dumps({
                "summary": "Checkout returned HTTP 502 because payment service declined transaction with card_issuer_declined.",
                "hypotheses": [
                    {
                        "id": "hyp_pay_01",
                        "description": "Downstream payment gateway declined authorization with card_issuer_declined (fraud check/insufficient funds).",
                        "status": "supported",
                        "supporting_evidence": ["ev_pay_span_chk", "ev_pay_span_svc", "ev_pay_log_01"],
                        "contradicting_evidence": [],
                        "missing_evidence": ["Gateway provider webhook raw payload"],
                        "next_step": "Inspect payment gateway webhook and decline audit logs for card_issuer_declined reason.",
                    }
                ]
            })
        elif "inc_eval_inv_oos" in prompt:
            return json.dumps({
                "summary": "Order submission failed with 409 Conflict because requested SKU is out of stock in warehouse-east.",
                "hypotheses": [
                    {
                        "id": "hyp_inv_01",
                        "description": "Inventory allocation failed due to out of stock condition for sku_laptop_stand in warehouse-east.",
                        "status": "supported",
                        "supporting_evidence": ["ev_inv_span_01", "ev_inv_log_01", "ev_inv_chk_log"],
                        "contradicting_evidence": [],
                        "missing_evidence": ["Warehouse restock schedule"],
                        "next_step": "Check warehouse inventory stock levels for sku_laptop_stand in warehouse-east and update product catalog.",
                    }
                ]
            })
        elif "inc_eval_elevated_err" in prompt:
            return json.dumps({
                "summary": "Elevated 5xx error rate (18.5%) post-deployment checkout-v2.2.0 caused by NullPointerException in CartItemsSerializer.",
                "hypotheses": [
                    {
                        "id": "hyp_err_01",
                        "description": "Deployment checkout-v2.2.0 introduced a NullPointerException in CartItemsSerializer when order.discounts is null.",
                        "status": "supported",
                        "supporting_evidence": ["ev_dep_event_01", "ev_ser_log_01", "ev_rate_met_01"],
                        "contradicting_evidence": [],
                        "missing_evidence": ["Unit test coverage on CartItemsSerializer"],
                        "next_step": "Roll back deployment checkout-v2.2.0 and review commit c4d5e6f diff for null checks.",
                    }
                ]
            })
        elif "inc_eval_lat_spike" in prompt:
            return json.dumps({
                "summary": "Inventory service latency breached 4500ms due to an unindexed sequential scan on inventory_items table.",
                "hypotheses": [
                    {
                        "id": "hyp_lat_01",
                        "description": "Database query performance degraded due to Seq Scan on inventory_items table lacking proper indexes.",
                        "status": "supported",
                        "supporting_evidence": ["ev_lat_span_01", "ev_lat_log_01", "ev_lat_met_01"],
                        "contradicting_evidence": [],
                        "missing_evidence": ["Table row count growth trend"],
                        "next_step": "Run EXPLAIN ANALYZE on inventory_items query and create missing index on sku and warehouse_id.",
                    }
                ]
            })
        elif "inc_eval_incomplete" in prompt:
            return json.dumps({
                "summary": "Checkout failed with HTTP 500 during remote orchestration, but downstream logs and traces are missing.",
                "hypotheses": [
                    {
                        "id": "hyp_inc_01",
                        "description": "Downstream RPC call failed; specific root cause cannot be determined due to missing downstream telemetry.",
                        "status": "inconclusive",
                        "supporting_evidence": ["ev_inc_span_01", "ev_inc_log_01"],
                        "contradicting_evidence": [],
                        "missing_evidence": ["Downstream Payment and Inventory service logs", "Distributed traces from downstream services"],
                        "next_step": "Inspect downstream service logs for inventory and payment microservices and verify collector ingestion.",
                    }
                ]
            })
        elif "inc_eval_ambiguous" in prompt:
            return json.dumps({
                "summary": "Checkout experienced timeouts while database CPU hit 95% and external fixer.io currency API returned 504.",
                "hypotheses": [
                    {
                        "id": "hyp_amb_01",
                        "description": "Database CPU saturation (95%) caused query queues and request timeouts.",
                        "status": "possible",
                        "supporting_evidence": ["ev_amb_db_cpu", "ev_amb_chk_span"],
                        "contradicting_evidence": [],
                        "missing_evidence": ["pg_stat_activity query profile"],
                        "next_step": "Correlate timeline between database query durations and external fixer.io API latency.",
                    },
                    {
                        "id": "hyp_amb_02",
                        "description": "External currency API fixer.io gateway timeout (504) delayed checkout transaction completion.",
                        "status": "possible",
                        "supporting_evidence": ["ev_amb_api_log", "ev_amb_chk_span"],
                        "contradicting_evidence": [],
                        "missing_evidence": ["Third party status page"],
                        "next_step": "Check fixer.io status page and configure circuit breaker or cache fallback.",
                    }
                ]
            })
        elif "inc_eval_contradictory" in prompt:
            return json.dumps({
                "summary": "Checkout failures caused by API Gateway token bucket rate limiting (429), contradicting operator deadlock suspicion.",
                "hypotheses": [
                    {
                        "id": "hyp_contra_01",
                        "description": "API Gateway token bucket rate limits were exceeded (500 req/sec), throttling incoming traffic. Suspected database deadlocks are contradicted by 0 deadlocks metric.",
                        "status": "supported",
                        "supporting_evidence": ["ev_contra_gw_log", "ev_contra_gw_span"],
                        "contradicting_evidence": ["ev_contra_met_deadlocks", "ev_contra_met_active_conn"],
                        "missing_evidence": ["Gateway burst limit configuration diff"],
                        "next_step": "Inspect API gateway rate limit quotas and token bucket burst settings.",
                    }
                ]
            })
        elif "inc_eval_insufficient" in prompt:
            return json.dumps({
                "summary": "Payment service abruptly terminated with connection reset; application telemetry is insufficient to determine cause.",
                "hypotheses": [
                    {
                        "id": "hyp_insuf_01",
                        "description": "Process terminated abruptly without application-level error logging; true cause is unidentifiable from telemetry alone.",
                        "status": "inconclusive",
                        "supporting_evidence": ["ev_insuf_log_01", "ev_insuf_span_01"],
                        "contradicting_evidence": [],
                        "missing_evidence": ["Host dmesg kernel logs", "Container cgroup memory limit metrics", "Core dump or fatal exit code"],
                        "next_step": "Inspect host dmesg and syslog for kernel OOMKilled events on payment service container.",
                    }
                ]
            })
        else:
            return json.dumps({
                "summary": "Generic incident investigation.",
                "hypotheses": [
                    {
                        "id": "hyp_gen_01",
                        "description": "Generic hypothesis.",
                        "status": "possible",
                        "supporting_evidence": [],
                        "contradicting_evidence": [],
                        "missing_evidence": ["All telemetry"],
                        "next_step": "Inspect service logs.",
                    }
                ]
            })

    mock.generate.side_effect = mock_generate
    return mock

async def main():
    parser = argparse.ArgumentParser(description="AI Incident Investigation Benchmark Evaluator")
    parser.add_argument("--mock", action="store_true", help="Use deterministic mock responses instead of live Ollama inference")
    parser.add_argument("--model", type=str, default=None, help="LLM model name (defaults to env LLM_MODEL or qwen3:4b)")
    parser.add_argument("--base-url", type=str, default=None, help="Ollama base URL (defaults to OLLAMA_BASE_URL)")
    parser.add_argument("--output-dir", type=str, default="eval_reports", help="Directory where evaluation reports will be saved")
    parser.add_argument("--scenario", type=str, default=None, help="Filter to run a single scenario ID")
    args = parser.parse_args()

    model_name = args.model or os.getenv("LLM_MODEL", settings.LLM_MODEL)
    base_url = args.base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11435")

    print("=" * 80)
    print("AI SOFTWARE INCIDENT INVESTIGATOR — EVALUATION BENCHMARK (STEP 9)")
    print("=" * 80)
    print(f"Dataset Version: v{EVALUATION_DATASET_VERSION} | Prompt Version: v{PROMPT_VERSION}")
    print(f"Target Model   : {model_name} ({'MOCK MODE' if args.mock else base_url})")
    print(f"Total Scenarios: {len(EVALUATION_SCENARIOS)}")
    print("=" * 80)

    if args.mock:
        client = create_mock_client()
    else:
        client = OllamaClient(base_url=base_url, model=model_name)

    runner = EvaluationRunner(client=client, model_name=model_name, base_url=base_url)

    scenarios = EVALUATION_SCENARIOS
    if args.scenario:
        scenarios = [s for s in scenarios if s.id == args.scenario]
        if not scenarios:
            print(f"Error: scenario '{args.scenario}' not found in dataset.", file=sys.stderr)
            sys.exit(1)

    print(f"\nRunning evaluation on {len(scenarios)} scenario(s)...")
    results = await runner.run_evaluation_suite(scenarios)

    output_dir = Path(args.output_dir)
    json_path, md_path = runner.save_reports(results, output_dir)

    # Print summary table
    agg = results["aggregate_metrics"]
    print("\n" + "=" * 80)
    print("EVALUATION BENCHMARK SUMMARY RESULTS")
    print("=" * 80)
    print(f"  Overall Benchmark Score       : {agg['overall_benchmark_score'] * 100:.1f}%")
    print(f"  Diagnosis Accuracy            : {agg['average_diagnosis_accuracy'] * 100:.1f}%")
    print(f"  Root Cause ID vs Symptom Rate : {agg['root_cause_identification_rate'] * 100:.1f}%")
    print(f"  Evidence Citation Validity    : {agg['average_citation_validity'] * 100:.1f}%")
    print(f"  Essential Evidence Recall     : {agg['average_evidence_recall'] * 100:.1f}%")
    print(f"  Evidence Precision            : {agg['average_evidence_precision'] * 100:.1f}%")
    print(f"  Unsupported Claim Rate        : {agg['average_unsupported_claim_rate'] * 100:.1f}%")
    print(f"  Uncertainty Handling Score    : {agg['average_uncertainty_score'] * 100:.1f}%")
    print(f"  Actionability Score           : {agg['average_actionability_score'] * 100:.1f}%")
    print(f"  Scenarios Requiring Review    : {agg['scenarios_requiring_human_review']} / {agg['total_scenarios']}")
    print("-" * 80)
    print(f"Reports saved to:")
    print(f"  - JSON Report    : {json_path}")
    print(f"  - Markdown Report: {md_path}")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())

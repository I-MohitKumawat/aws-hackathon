#!/usr/bin/env python3
"""
Step 9 Verification Script: AI Investigation Evaluation Benchmark
Validates:
1. Evaluation Dataset integrity (9 scenarios covering root causes, incomplete, ambiguous, contradictory, and insufficient telemetry).
2. Deterministic Scorer:
   - Root Cause vs Symptom distinction
   - Citation validity & fabricated citation detection
   - Essential evidence recall & noise precision
   - Overconfident hallucination detection on insufficient telemetry
   - Actionability & specificity scoring
3. Evaluation Harness:
   - Full evaluation execution
   - Structured JSON results generation (eval_reports/evaluation_results.json)
   - Formatted Markdown benchmark report (eval_reports/evaluation_report.md)
4. Live Model Benchmark:
   - Evaluates configured Ollama model (qwen3:4b) against the dataset
   - Records empirical diagnosis accuracy, evidence grounding, uncertainty handling, and actionability
"""

import os
import sys
import json
import time
import asyncio
from pathlib import Path
from datetime import datetime, timezone
import httpx as requests

from backend.app.config import settings
from backend.app.agent import OllamaClient
from backend.app.evaluation import (
    EVALUATION_SCENARIOS,
    EVALUATION_DATASET_VERSION,
    PROMPT_VERSION,
    ScenarioCategory,
    EvaluationScorer,
    EvaluationRunner,
)
from scripts.evaluate_investigation import create_mock_client

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000/api/v1")
AUTH_HEADERS = {"X-API-Key": "dev-admin-key"}
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11435")
MODEL_NAME = os.getenv("LLM_MODEL", settings.LLM_MODEL)

def log(msg: str):
    now = datetime.now(timezone.utc).strftime("%H:%M:%S")
    print(f"[{now}] {msg}")

def check_connectivity():
    log("=" * 75)
    log("1. Checking Environment & Service Connectivity")
    log("=" * 75)

    services = [
        ("Backend Health", f"{BACKEND_URL}/health", AUTH_HEADERS),
        ("Ollama Tags", f"{OLLAMA_BASE_URL}/api/tags", {}),
    ]

    all_ok = True
    for name, url, headers in services:
        try:
            r = requests.get(url, headers=headers, timeout=5)
            log(f"  [OK] {name:<22} ({r.status_code}) -> {url}")
        except Exception as e:
            log(f"  [FAIL] {name:<22} -> {e}")
            all_ok = False

    return all_ok

async def run_verification():
    log("\n" + "=" * 75)
    log("2. Starting Step 9 AI Investigation Evaluation Verification")
    log("=" * 75)

    # -----------------------------------------------------------------
    # Step 1: Verify Evaluation Dataset Structure & Integrity
    # -----------------------------------------------------------------
    log("\n--- Step 1: Verifying Evaluation Dataset Integrity ---")
    assert len(EVALUATION_SCENARIOS) == 9, f"Expected 9 scenarios, got {len(EVALUATION_SCENARIOS)}"
    categories = {s.category for s in EVALUATION_SCENARIOS}
    expected_categories = {
        ScenarioCategory.ROOT_CAUSE_KNOWN,
        ScenarioCategory.INCOMPLETE_EVIDENCE,
        ScenarioCategory.AMBIGUOUS_EVIDENCE,
        ScenarioCategory.CONTRADICTORY_EVIDENCE,
        ScenarioCategory.INSUFFICIENT_TELEMETRY,
    }
    assert categories == expected_categories, f"Missing categories: {expected_categories - categories}"
    log(f"  [PASS] All 9 scenarios loaded covering 5 categories: {[c.value for c in categories]}")

    for s in EVALUATION_SCENARIOS:
        inc, ev_list = s.to_models()
        assert inc.id == s.incident_data["id"]
        assert len(ev_list) == len(s.evidence_data)
        assert len(s.ground_truth.essential_evidence_ids) >= 1
    log("  [PASS] In-memory model conversion validated without database pollution.")

    # -----------------------------------------------------------------
    # Step 2: Verify Deterministic Scorer Edge Cases
    # -----------------------------------------------------------------
    log("\n--- Step 2: Testing Scorer Edge Cases & Scoring Invariants ---")
    scen_db = next(s for s in EVALUATION_SCENARIOS if s.id == "scen_db_pool_exhaustion")
    from backend.app.schemas.report import Hypothesis
    from backend.app.agent.validator import RawAIInvestigationOutput

    # Test root cause vs symptom
    symp_output = RawAIInvestigationOutput(
        summary="Checkout order submission failed with HTTP 500 error.",
        hypotheses=[
            Hypothesis(
                id="hyp_s",
                description="Orders failed with 500 status code.",
                status="possible",
                supporting_evidence=["ev_db_span_01"],
                contradicting_evidence=[],
                missing_evidence=[],
                next_step="Inspect server logs.",
            )
        ]
    )
    res_symp = EvaluationScorer.evaluate_scenario(scen_db, symp_output)
    assert res_symp.diagnosis_status == "partially_identified"
    assert res_symp.identified_root_cause_vs_symptom is False
    assert res_symp.diagnosis_accuracy_score == 0.5
    log("  [PASS] Symptom-only diagnosis accurately scored at 0.5 (partially_identified, root_cause=False).")

    # Test fabricated citation penalty
    fab_output = RawAIInvestigationOutput(
        summary="Checkout pool exhaustion.",
        hypotheses=[
            Hypothesis(
                id="hyp_f",
                description="PostgreSQL pool exhausted at 20 connections.",
                status="supported",
                supporting_evidence=["ev_db_span_01", "ev_FABRICATED_0001"],
                contradicting_evidence=[],
                missing_evidence=[],
                next_step="Inspect pg_stat_activity.",
            )
        ]
    )
    res_fab = EvaluationScorer.evaluate_scenario(scen_db, fab_output)
    assert res_fab.invalid_citations_count == 1
    assert res_fab.citation_validity_rate == 0.5
    assert res_fab.hallucination_detected is True
    log("  [PASS] Fabricated citation detected: citation_validity_rate=0.5, hallucination_detected=True.")

    # Test unidentifiable telemetry uncertainty handling
    scen_insuf = next(s for s in EVALUATION_SCENARIOS if s.id == "scen_insufficient_telemetry")
    incon_output = RawAIInvestigationOutput(
        summary="Payment service process crashed with connection reset; telemetry is insufficient.",
        hypotheses=[
            Hypothesis(
                id="hyp_i",
                description="Abrupt termination; root cause is unidentifiable from telemetry alone.",
                status="inconclusive",
                supporting_evidence=["ev_insuf_log_01", "ev_insuf_span_01"],
                contradicting_evidence=[],
                missing_evidence=["Host dmesg kernel logs", "OOMKilled events"],
                next_step="Check host dmesg and syslog for kernel OOMKilled events.",
            )
        ]
    )
    res_incon = EvaluationScorer.evaluate_scenario(scen_insuf, incon_output)
    assert res_incon.diagnosis_status == "identified"
    assert res_incon.uncertainty_score == 1.0
    assert res_incon.hallucination_detected is False
    log("  [PASS] Inconclusive status on unidentifiable scenario correctly rewarded with uncertainty_score=1.0.")

    # -----------------------------------------------------------------
    # Step 3: Verify Evaluation Harness Execution
    # -----------------------------------------------------------------
    log("\n--- Step 3: Testing Full Evaluation Harness & Report Generation ---")
    mock_client = create_mock_client()
    runner = EvaluationRunner(client=mock_client, model_name="mock_benchmark_model")
    results = await runner.run_evaluation_suite(EVALUATION_SCENARIOS)

    assert results["metadata"]["total_scenarios"] == 9
    agg = results["aggregate_metrics"]
    assert agg["overall_benchmark_score"] >= 0.85
    assert agg["average_citation_validity"] == 1.0

    out_dir = Path("eval_reports")
    json_path, md_path = runner.save_reports(results, out_dir)
    assert json_path.exists()
    assert md_path.exists()
    log(f"  [PASS] Harness execution complete. Saved:\n    - {json_path}\n    - {md_path}")

    # -----------------------------------------------------------------
    # Step 4: Run Live Ollama Benchmark
    # -----------------------------------------------------------------
    log(f"\n--- Step 4: Executing Live Ollama Evaluation against Model '{MODEL_NAME}' ---")
    log(f"Connecting to Ollama at {OLLAMA_BASE_URL}...")
    live_client = OllamaClient(base_url=OLLAMA_BASE_URL, model=MODEL_NAME)
    live_runner = EvaluationRunner(client=live_client, model_name=MODEL_NAME, base_url=OLLAMA_BASE_URL)

    # Run on full scenario set
    live_results = await live_runner.run_evaluation_suite(EVALUATION_SCENARIOS)
    live_json_path, live_md_path = live_runner.save_reports(live_results, out_dir)

    live_agg = live_results["aggregate_metrics"]
    log("\n" + "=" * 75)
    log("LIVE BENCHMARK RESULTS FOR " + MODEL_NAME)
    log("=" * 75)
    log(f"  Overall Benchmark Score       : {live_agg['overall_benchmark_score'] * 100:.1f}%")
    log(f"  Diagnosis Accuracy            : {live_agg['average_diagnosis_accuracy'] * 100:.1f}%")
    log(f"  Root Cause ID vs Symptom Rate : {live_agg['root_cause_identification_rate'] * 100:.1f}%")
    log(f"  Evidence Citation Validity    : {live_agg['average_citation_validity'] * 100:.1f}%")
    log(f"  Essential Evidence Recall     : {live_agg['average_evidence_recall'] * 100:.1f}%")
    log(f"  Evidence Precision            : {live_agg['average_evidence_precision'] * 100:.1f}%")
    log(f"  Unsupported Claim Rate        : {live_agg['average_unsupported_claim_rate'] * 100:.1f}%")
    log(f"  Uncertainty Handling Score    : {live_agg['average_uncertainty_score'] * 100:.1f}%")
    log(f"  Actionability Score           : {live_agg['average_actionability_score'] * 100:.1f}%")
    log(f"  Scenarios Requiring Review    : {live_agg['scenarios_requiring_human_review']} / {live_agg['total_scenarios']}")
    log("=" * 75)

    log(f"\nLive reports successfully written to:\n  {live_json_path}\n  {live_md_path}")
    log("\nSTEP 9 AI INVESTIGATION EVALUATION COMPLETED SUCCESSFULLY!")

def main():
    if not check_connectivity():
        log("[WARN] Connectivity check failed for one or more services. Proceeding with caution.")
    asyncio.run(run_verification())

if __name__ == "__main__":
    main()

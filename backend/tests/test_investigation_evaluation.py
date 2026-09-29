import pytest
import json
from unittest.mock import AsyncMock
from pathlib import Path

from backend.app.schemas.report import Hypothesis
from backend.app.agent.validator import RawAIInvestigationOutput
from backend.app.evaluation import (
    EVALUATION_SCENARIOS,
    ScenarioCategory,
    EvaluationScorer,
    EvaluationRunner,
    ScenarioEvaluationResult,
    AggregateEvaluationMetrics,
)
from backend.app.agent import OllamaClient
from scripts.evaluate_investigation import create_mock_client

def test_evaluation_dataset_completeness():
    assert len(EVALUATION_SCENARIOS) == 9
    categories = {s.category for s in EVALUATION_SCENARIOS}
    assert ScenarioCategory.ROOT_CAUSE_KNOWN in categories
    assert ScenarioCategory.INCOMPLETE_EVIDENCE in categories
    assert ScenarioCategory.AMBIGUOUS_EVIDENCE in categories
    assert ScenarioCategory.CONTRADICTORY_EVIDENCE in categories
    assert ScenarioCategory.INSUFFICIENT_TELEMETRY in categories

    for s in EVALUATION_SCENARIOS:
        assert s.id.startswith("scen_")
        assert len(s.incident_data["title"]) > 5
        assert len(s.evidence_data) >= 2
        assert len(s.ground_truth.primary_cause_keywords) >= 1
        assert len(s.ground_truth.expected_diagnostic_actions) >= 1
        assert len(s.ground_truth.essential_evidence_ids) >= 1

        # Test in-memory model instantiation
        inc, ev_list = s.to_models()
        assert inc.id == s.incident_data["id"]
        assert len(ev_list) == len(s.evidence_data)
        for ev in ev_list:
            assert ev.incident_id == inc.id

def test_diagnosis_accuracy_root_cause_vs_symptom():
    scen = next(s for s in EVALUATION_SCENARIOS if s.id == "scen_db_pool_exhaustion")

    # 1. Output identifies actual root cause
    rc_output = RawAIInvestigationOutput(
        summary="Checkout order submission failed due to PostgreSQL connection pool exhaustion.",
        hypotheses=[
            Hypothesis(
                id="hyp_1",
                description="Database connection pool was saturated at 20/20 active connections.",
                status="supported",
                supporting_evidence=["ev_db_span_01", "ev_db_log_01", "ev_db_met_01"],
                contradicting_evidence=[],
                missing_evidence=[],
                next_step="Inspect pg_stat_activity for long running transactions.",
            )
        ],
    )
    res_rc = EvaluationScorer.evaluate_scenario(scen, rc_output)
    assert res_rc.diagnosis_status == "identified"
    assert res_rc.diagnosis_accuracy_score == 1.0
    assert res_rc.identified_root_cause_vs_symptom is True

    # 2. Output identifies only symptom (e.g. 500 error / checkout failure) without root cause mechanism
    symptom_output = RawAIInvestigationOutput(
        summary="Checkout service failed to process orders and returned HTTP 500 error to users.",
        hypotheses=[
            Hypothesis(
                id="hyp_1",
                description="Order failure caused by 500 internal server error during order submission.",
                status="possible",
                supporting_evidence=["ev_db_span_01"],
                contradicting_evidence=[],
                missing_evidence=["Database logs"],
                next_step="Check general server logs.",
            )
        ],
    )
    res_sym = EvaluationScorer.evaluate_scenario(scen, symptom_output)
    assert res_sym.diagnosis_status == "partially_identified"
    assert res_sym.diagnosis_accuracy_score == 0.5
    assert res_sym.identified_root_cause_vs_symptom is False

    # 3. Output completely misses cause and symptom
    wrong_output = RawAIInvestigationOutput(
        summary="Payment gateway credit card fraud check failed due to invalid CVV.",
        hypotheses=[
            Hypothesis(
                id="hyp_1",
                description="User entered invalid card credentials causing authentication failure.",
                status="possible",
                supporting_evidence=[],
                contradicting_evidence=[],
                missing_evidence=[],
                next_step="Ask user to re-enter card.",
            )
        ],
    )
    res_wrong = EvaluationScorer.evaluate_scenario(scen, wrong_output)
    assert res_wrong.diagnosis_status == "missed"
    assert res_wrong.diagnosis_accuracy_score == 0.0
    assert res_wrong.identified_root_cause_vs_symptom is False

def test_evidence_grounding_and_fabricated_citations():
    scen = next(s for s in EVALUATION_SCENARIOS if s.id == "scen_inventory_out_of_stock")

    # Output with fabricated evidence ID
    bad_citation_output = RawAIInvestigationOutput(
        summary="Inventory allocation failed: item out of stock.",
        hypotheses=[
            Hypothesis(
                id="hyp_1",
                description="Item out of stock in warehouse-east.",
                status="supported",
                supporting_evidence=["ev_inv_span_01", "ev_FABRICATED_9999"],
                contradicting_evidence=[],
                missing_evidence=[],
                next_step="Check warehouse stock in warehouse-east.",
            )
        ],
    )
    res = EvaluationScorer.evaluate_scenario(scen, bad_citation_output)
    assert res.invalid_citations_count == 1
    assert res.citation_validity_rate == 0.5
    assert res.hallucination_detected is True
    assert res.unsupported_claims_count >= 1

def test_uncertainty_handling_on_insufficient_telemetry():
    scen = next(s for s in EVALUATION_SCENARIOS if s.id == "scen_insufficient_telemetry")

    # 1. Good: Model correctly recognizes insufficient telemetry, marks inconclusive
    inconclusive_output = RawAIInvestigationOutput(
        summary="Payment service terminated abruptly with connection reset; telemetry is insufficient to determine cause.",
        hypotheses=[
            Hypothesis(
                id="hyp_1",
                description="Process terminated without application traces; true cause cannot be determined.",
                status="inconclusive",
                supporting_evidence=["ev_insuf_log_01", "ev_insuf_span_01"],
                contradicting_evidence=[],
                missing_evidence=["Host dmesg kernel logs", "Container OOMKilled events"],
                next_step="Inspect host dmesg and syslog for kernel OOMKilled events.",
            )
        ],
    )
    res_good = EvaluationScorer.evaluate_scenario(scen, inconclusive_output)
    assert res_good.diagnosis_status == "identified"
    assert res_good.uncertainty_score == 1.0
    assert res_good.hallucination_detected is False

    # 2. Bad: Model overconfidently claims a specific software bug is "supported"
    hallucinated_output = RawAIInvestigationOutput(
        summary="Payment service crashed due to a memory leak in redis cache connection pool.",
        hypotheses=[
            Hypothesis(
                id="hyp_1",
                description="Redis cache connection pool leaked memory causing fatal crash.",
                status="supported",  # CONFIDENT BUT UNFOUNDED!
                supporting_evidence=["ev_insuf_log_01"],
                contradicting_evidence=[],
                missing_evidence=[],
                next_step="Restart redis cache server.",
            )
        ],
    )
    res_bad = EvaluationScorer.evaluate_scenario(scen, hallucinated_output)
    assert res_bad.diagnosis_status == "missed"
    assert res_bad.uncertainty_score == 0.0
    assert res_bad.hallucination_detected is True
    assert res_bad.unsupported_claims_count >= 1

def test_actionability_scoring_specific_vs_vague():
    scen = next(s for s in EVALUATION_SCENARIOS if s.id == "scen_sustained_latency_spike")

    # Specific action with diagnostic tools and table names
    specific_output = RawAIInvestigationOutput(
        summary="Inventory latency spike caused by unindexed sequential scan on inventory_items.",
        hypotheses=[
            Hypothesis(
                id="hyp_1",
                description="Sequential scan on inventory_items.",
                status="supported",
                supporting_evidence=["ev_lat_span_01", "ev_lat_log_01", "ev_lat_met_01"],
                contradicting_evidence=[],
                missing_evidence=[],
                next_step="Run EXPLAIN ANALYZE on query and add index on inventory_items(sku, warehouse_id).",
            )
        ],
    )
    res_spec = EvaluationScorer.evaluate_scenario(scen, specific_output)
    assert res_spec.action_specificity_score >= 0.7
    assert res_spec.actionability_score >= 0.8

    # Vague action
    vague_output = RawAIInvestigationOutput(
        summary="Inventory latency spike caused by unindexed sequential scan on inventory_items.",
        hypotheses=[
            Hypothesis(
                id="hyp_1",
                description="Sequential scan on inventory_items.",
                status="supported",
                supporting_evidence=["ev_lat_span_01", "ev_lat_log_01", "ev_lat_met_01"],
                contradicting_evidence=[],
                missing_evidence=[],
                next_step="Check system logs and fix the slow code.",
            )
        ],
    )
    res_vague = EvaluationScorer.evaluate_scenario(scen, vague_output)
    assert res_vague.action_specificity_score <= 0.4
    assert res_vague.actionability_score < res_spec.actionability_score

@pytest.mark.asyncio
async def test_evaluation_runner_mock_full_suite(tmp_path: Path):
    mock_client = create_mock_client()
    runner = EvaluationRunner(client=mock_client, model_name="test_model_mock")

    results = await runner.run_evaluation_suite(EVALUATION_SCENARIOS)

    assert results["metadata"]["total_scenarios"] == 9
    assert results["metadata"]["model_name"] == "test_model_mock"
    assert len(results["scenario_results"]) == 9

    agg = results["aggregate_metrics"]
    assert agg["overall_benchmark_score"] >= 0.80
    assert agg["average_diagnosis_accuracy"] >= 0.80
    assert agg["average_citation_validity"] == 1.0

    # Test report formatting and persistence
    json_path, md_path = runner.save_reports(results, tmp_path)
    assert json_path.exists()
    assert md_path.exists()

    with open(json_path, "r", encoding="utf-8") as f:
        saved_json = json.load(f)
        assert saved_json["metadata"]["total_scenarios"] == 9

    with open(md_path, "r", encoding="utf-8") as f:
        saved_md = f.read()
        assert "# AI Incident Investigation Benchmark Report" in saved_md
        assert "scen_db_pool_exhaustion" in saved_md

@pytest.mark.asyncio
async def test_evaluation_runner_handles_scenario_exception():
    failing_client = AsyncMock(spec=OllamaClient)
    failing_client.generate.side_effect = RuntimeError("Ollama connection severed")

    runner = EvaluationRunner(client=failing_client, model_name="failing_model")
    scen = EVALUATION_SCENARIOS[:1]

    results = await runner.run_evaluation_suite(scen)
    assert len(results["scenario_results"]) == 1
    res = results["scenario_results"][0]
    assert res["diagnosis_status"] == "missed"
    assert res["composite_score"] == 0.0
    assert res["human_review_required"] is True

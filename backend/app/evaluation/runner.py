import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

from .dataset import (
    EvaluationScenario,
    EVALUATION_SCENARIOS,
    EVALUATION_DATASET_VERSION,
)
from .scorer import (
    EvaluationScorer,
    ScenarioEvaluationResult,
    AggregateEvaluationMetrics,
)
from ..agent import OllamaClient, RawAIInvestigationOutput, ReportValidationError
from ..services.investigation_service import investigate_incident
from ..config import settings

logger = logging.getLogger(__name__)

PROMPT_VERSION = "1.0.0"

class EvaluationReportData(dict):
    """Container for full serialized evaluation results."""
    pass

class EvaluationRunner:
    def __init__(
        self,
        client: Optional[OllamaClient] = None,
        model_name: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.model_name = model_name or settings.LLM_MODEL
        self.base_url = base_url or settings.OLLAMA_BASE_URL
        self.client = client or OllamaClient(base_url=self.base_url, model=self.model_name)

    async def evaluate_single_scenario(
        self,
        scenario: EvaluationScenario,
    ) -> tuple[ScenarioEvaluationResult, RawAIInvestigationOutput, float]:
        """Runs investigation on a single scenario and computes evaluation scores."""
        incident, evidence_items = scenario.to_models()
        t0 = time.time()
        output = await investigate_incident(
            incident=incident,
            evidence_items=evidence_items,
            client=self.client,
        )
        duration = round(time.time() - t0, 2)
        score_result = EvaluationScorer.evaluate_scenario(scenario, output)
        return score_result, output, duration

    async def run_evaluation_suite(
        self,
        scenarios: Optional[List[EvaluationScenario]] = None,
    ) -> Dict[str, Any]:
        """Runs the complete evaluation suite across all scenarios and compiles aggregate metrics."""
        eval_scenarios = scenarios or EVALUATION_SCENARIOS
        start_time = datetime.now(timezone.utc)
        overall_t0 = time.time()

        scenario_evaluations: List[ScenarioEvaluationResult] = []
        raw_outputs: Dict[str, Dict[str, Any]] = {}
        execution_durations: Dict[str, float] = {}

        for scenario in eval_scenarios:
            logger.info("Evaluating scenario '%s' (%s)...", scenario.id, scenario.name)
            try:
                score_result, output, duration = await self.evaluate_single_scenario(scenario)
                scenario_evaluations.append(score_result)
                raw_outputs[scenario.id] = output.model_dump()
                execution_durations[scenario.id] = duration
            except Exception as exc:
                logger.error("Failed to evaluate scenario '%s': %s", scenario.id, exc, exc_info=True)
                # Create a penalized failure result
                fallback_result = ScenarioEvaluationResult(
                    scenario_id=scenario.id,
                    scenario_name=scenario.name,
                    category=scenario.category,
                    diagnosis_status="missed",
                    diagnosis_accuracy_score=0.0,
                    identified_root_cause_vs_symptom=False,
                    diagnosis_explanation=f"Investigation failed with exception: {exc}",
                    total_citations=0,
                    valid_citations_count=0,
                    invalid_citations_count=0,
                    citation_validity_rate=0.0,
                    essential_evidence_cited=[],
                    essential_evidence_missing=scenario.ground_truth.essential_evidence_ids,
                    essential_evidence_recall=0.0,
                    irrelevant_evidence_cited=[],
                    evidence_precision=0.0,
                    grounding_score=0.0,
                    unsupported_claims_count=1,
                    unsupported_claim_rate=1.0,
                    uncertainty_score=0.0,
                    hallucination_detected=True,
                    uncertainty_explanation="Model failed to produce valid report.",
                    matched_action_keywords=[],
                    action_alignment_score=0.0,
                    action_specificity_score=0.0,
                    actionability_score=0.0,
                    composite_score=0.0,
                    human_review_required=True,
                    qualitative_notes=f"Exception encountered: {str(exc)}",
                )
                scenario_evaluations.append(fallback_result)
                execution_durations[scenario.id] = 0.0

        total_duration = round(time.time() - overall_t0, 2)
        aggregate_metrics = EvaluationScorer.aggregate_results(scenario_evaluations)

        payload = {
            "metadata": {
                "timestamp": start_time.isoformat(),
                "model_name": self.model_name,
                "base_url": self.base_url,
                "prompt_version": PROMPT_VERSION,
                "dataset_version": EVALUATION_DATASET_VERSION,
                "total_scenarios": len(eval_scenarios),
                "duration_seconds": total_duration,
            },
            "aggregate_metrics": aggregate_metrics.model_dump(),
            "scenario_results": [res.model_dump() for res in scenario_evaluations],
            "raw_outputs": raw_outputs,
            "execution_durations": execution_durations,
        }
        return payload

    @classmethod
    def format_markdown_report(cls, results_data: Dict[str, Any]) -> str:
        """Renders comprehensive Markdown evaluation report."""
        meta = results_data["metadata"]
        agg = results_data["aggregate_metrics"]
        scenarios = results_data["scenario_results"]

        report = f"""# AI Incident Investigation Benchmark Report

**Date**: {meta['timestamp']}  
**Evaluated Model**: `{meta['model_name']}`  
**Dataset Version**: `v{meta['dataset_version']}` | **Prompt Version**: `v{meta['prompt_version']}`  
**Total Scenarios**: {meta['total_scenarios']} | **Total Execution Time**: {meta['duration_seconds']}s  

---

## 1. Executive Summary & Aggregate Metrics

| Benchmark Metric | Score | Target Standard | Assessment |
|---|---|---|---|
| **Overall Benchmark Index** | **{agg['overall_benchmark_score'] * 100:.1f}%** | $\\ge$ 75.0% | {'PASS' if agg['overall_benchmark_score'] >= 0.75 else 'NEEDS IMPROVEMENT'} |
| **Diagnosis Accuracy** | **{agg['average_diagnosis_accuracy'] * 100:.1f}%** | $\\ge$ 80.0% | {'PASS' if agg['average_diagnosis_accuracy'] >= 0.80 else 'ACCEPTABLE' if agg['average_diagnosis_accuracy'] >= 0.60 else 'FAIL'} |
| **Root Cause ID vs Symptom Rate** | **{agg['root_cause_identification_rate'] * 100:.1f}%** | $\\ge$ 70.0% | {'PASS' if agg['root_cause_identification_rate'] >= 0.70 else 'DEFICIT'} |
| **Evidence Citation Validity** | **{agg['average_citation_validity'] * 100:.1f}%** | 100.0% | {'PASS' if agg['average_citation_validity'] >= 0.99 else 'HALLUCINATION RISK'} |
| **Essential Evidence Recall** | **{agg['average_evidence_recall'] * 100:.1f}%** | $\\ge$ 75.0% | {'PASS' if agg['average_evidence_recall'] >= 0.75 else 'GAPS DETECTED'} |
| **Evidence Precision** | **{agg['average_evidence_precision'] * 100:.1f}%** | $\\ge$ 80.0% | {'PASS' if agg['average_evidence_precision'] >= 0.80 else 'NOISE INCLUDED'} |
| **Unsupported Claim Rate** | **{agg['average_unsupported_claim_rate'] * 100:.1f}%** | $\\le$ 15.0% | {'PASS' if agg['average_unsupported_claim_rate'] <= 0.15 else 'OVERCONFIDENT'} |
| **Uncertainty Handling Score** | **{agg['average_uncertainty_score'] * 100:.1f}%** | $\\ge$ 70.0% | {'PASS' if agg['average_uncertainty_score'] >= 0.70 else 'DEFICIT'} |
| **Diagnostic Actionability** | **{agg['average_actionability_score'] * 100:.1f}%** | $\\ge$ 70.0% | {'PASS' if agg['average_actionability_score'] >= 0.70 else 'GENERIC ACTIONS'} |
| **Human Review Required** | **{agg['scenarios_requiring_human_review']}/{agg['total_scenarios']}** | $\\le$ 3 | {'ACCEPTABLE' if agg['scenarios_requiring_human_review'] <= 3 else 'MANUAL TRIAGE NEEDED'} |

---

## 2. Per-Scenario Evaluation Breakdown

| Scenario ID | Category | Diagnosis Status | Root Cause? | Citation Valid | Evidence Recall | Uncertainty Score | Actionability | Composite Score |
|---|---|---|:---:|:---:|:---:|:---:|:---:|:---:|
"""
        for sc in scenarios:
            rc_sym = "True" if sc["identified_root_cause_vs_symptom"] else "False"
            report += (
                f"| `{sc['scenario_id']}` | `{sc['category']}` | **{sc['diagnosis_status'].upper()}** | "
                f"{rc_sym} | {sc['citation_validity_rate']*100:.0f}% | {sc['essential_evidence_recall']*100:.0f}% | "
                f"{sc['uncertainty_score']*100:.0f}% | {sc['actionability_score']*100:.0f}% | "
                f"**{sc['composite_score']*100:.1f}%** |\n"
            )

        report += """
---

## 3. Detailed Scenario Findings

"""
        for sc in scenarios:
            report += f"""### `{sc['scenario_id']}`: {sc['scenario_name']}
- **Category**: `{sc['category']}`
- **Diagnosis**: {sc['diagnosis_status']} ({sc['diagnosis_accuracy_score']*100:.0f}%) — {sc['diagnosis_explanation']}
- **Evidence Grounding**:
  - Valid Citations: {sc['valid_citations_count']}/{sc['total_citations']} ({sc['citation_validity_rate']*100:.0f}%)
  - Essential Evidence Cited: `{sc['essential_evidence_cited']}`
  - Essential Evidence Missing: `{sc['essential_evidence_missing']}`
  - Recall: {sc['essential_evidence_recall']*100:.0f}% | Precision: {sc['evidence_precision']*100:.0f}%
- **Uncertainty & Hallucination**:
  - Score: {sc['uncertainty_score']*100:.0f}% | Unsupported Claims: {sc['unsupported_claims_count']} ({sc['unsupported_claim_rate']*100:.0f}%)
  - Hallucination Detected: **{sc['hallucination_detected']}**
  - Notes: {sc['uncertainty_explanation']}
- **Diagnostic Actionability**:
  - Matched Action Keywords: `{sc['matched_action_keywords']}`
  - Action Alignment: {sc['action_alignment_score']*100:.0f}% | Specificity: {sc['action_specificity_score']*100:.0f}% | Total: {sc['actionability_score']*100:.0f}%
- **Composite Score**: **{sc['composite_score']*100:.1f}%** | **Human Review Flag**: {sc['human_review_required']}

"""

        report += """---

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
"""
        return report

    def save_reports(
        self,
        results_data: Dict[str, Any],
        output_dir: Path,
    ) -> tuple[Path, Path]:
        """Saves evaluation_results.json and evaluation_report.md into output_dir."""
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "evaluation_results.json"
        md_path = output_dir / "evaluation_report.md"

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(results_data, f, indent=2)

        markdown_content = self.format_markdown_report(results_data)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)

        return json_path, md_path

from typing import List, Dict, Any, Optional, Set
from pydantic import BaseModel, Field

from .dataset import EvaluationScenario, ScenarioCategory
from ..agent.validator import RawAIInvestigationOutput

class ScenarioEvaluationResult(BaseModel):
    scenario_id: str
    scenario_name: str
    category: ScenarioCategory

    # 1. Diagnosis Accuracy
    diagnosis_status: str  # "identified", "partially_identified", "missed"
    diagnosis_accuracy_score: float  # 0.0 - 1.0
    identified_root_cause_vs_symptom: bool
    diagnosis_explanation: str

    # 2. Evidence Grounding
    total_citations: int
    valid_citations_count: int
    invalid_citations_count: int
    citation_validity_rate: float  # 0.0 - 1.0
    essential_evidence_cited: List[str]
    essential_evidence_missing: List[str]
    essential_evidence_recall: float  # 0.0 - 1.0
    irrelevant_evidence_cited: List[str]
    evidence_precision: float  # 0.0 - 1.0
    grounding_score: float  # 0.0 - 1.0

    # 3. Uncertainty & Hallucinations
    unsupported_claims_count: int
    unsupported_claim_rate: float  # 0.0 - 1.0
    uncertainty_score: float  # 0.0 - 1.0
    hallucination_detected: bool
    uncertainty_explanation: str

    # 4. Actionability
    matched_action_keywords: List[str]
    action_alignment_score: float  # 0.0 - 1.0
    action_specificity_score: float  # 0.0 - 1.0
    actionability_score: float  # 0.0 - 1.0

    # 5. Composite & Review
    composite_score: float  # 0.0 - 1.0
    human_review_required: bool
    qualitative_notes: str

class AggregateEvaluationMetrics(BaseModel):
    total_scenarios: int
    evaluated_scenarios: int
    average_diagnosis_accuracy: float
    root_cause_identification_rate: float
    average_citation_validity: float
    average_evidence_recall: float
    average_evidence_precision: float
    average_unsupported_claim_rate: float
    average_uncertainty_score: float
    average_actionability_score: float
    overall_benchmark_score: float
    scenarios_requiring_human_review: int

class EvaluationScorer:
    """Deterministic evaluation scoring engine for incident investigation reports."""

    SPECIFICITY_MARKERS = [
        "pg_stat_activity", "pg_stat_database", "dmesg", "syslog", "explain analyze",
        "explain", "index", "rollback", "revert", "cgroup", "oomkilled", "token bucket",
        "rate limit", "warehouse", "sku", "connection pool", "max_connections",
        "504 gateway", "card_issuer_declined", "nullpointerexception", "cartitemsserializer",
        "circuit breaker", "cache", "config", "core dump"
    ]

    @classmethod
    def evaluate_scenario(
        cls,
        scenario: EvaluationScenario,
        output: RawAIInvestigationOutput,
    ) -> ScenarioEvaluationResult:
        gt = scenario.ground_truth
        valid_ev_ids = {ev["id"] for ev in scenario.evidence_data}

        # Collect text from summary and hypotheses (including missing_evidence)
        full_text = output.summary.lower()
        hyp_texts = [
            f"{h.id} {h.description} {h.next_step} {' '.join(h.missing_evidence)}".lower()
            for h in output.hypotheses
        ]
        combined_text = full_text + " " + " ".join(hyp_texts)

        # -------------------------------------------------------------
        # 1. Diagnosis Accuracy & Root Cause vs Symptom
        # -------------------------------------------------------------
        primary_matches = [kw for kw in gt.primary_cause_keywords if kw.lower() in combined_text]
        symptom_matches = [kw for kw in gt.symptom_keywords if kw.lower() in combined_text]

        if not gt.true_cause_identifiable:
            # For insufficient or incomplete evidence, correctly acknowledging uncertainty/unidentifiable IS the right diagnosis
            uncertainty_words = [
                "insufficient", "inconclusive", "cannot be determined", "unknown", "missing",
                "unidentifiable", "not captured", "no downstream telemetry", "unreachable",
                "absent", "lacking"
            ]
            acknowledged_unidentifiable = any(w in combined_text for w in uncertainty_words)
            has_supported_hyp = any(h.status == "supported" for h in output.hypotheses)

            if acknowledged_unidentifiable and not has_supported_hyp:
                diagnosis_status = "identified"
                diagnosis_accuracy_score = 1.0
                identified_rc = True
                diag_expl = "Correctly concluded root cause is unidentifiable from available telemetry."
            elif acknowledged_unidentifiable and has_supported_hyp:
                diagnosis_status = "partially_identified"
                diagnosis_accuracy_score = 0.5
                identified_rc = False
                diag_expl = "Mentioned missing telemetry, but overconfidently marked a hypothesis as supported."
            else:
                diagnosis_status = "missed"
                diagnosis_accuracy_score = 0.0
                identified_rc = False
                diag_expl = "Failed to recognize that telemetry was insufficient; claimed false certainty."
        else:
            if primary_matches:
                diagnosis_status = "identified"
                diagnosis_accuracy_score = 1.0
                identified_rc = True
                diag_expl = f"Identified primary root cause mechanism: {primary_matches}."
            elif symptom_matches:
                diagnosis_status = "partially_identified"
                diagnosis_accuracy_score = 0.5
                identified_rc = False
                diag_expl = f"Identified observed symptoms only {symptom_matches}, but missed underlying root cause mechanism."
            else:
                diagnosis_status = "missed"
                diagnosis_accuracy_score = 0.0
                identified_rc = False
                diag_expl = "Failed to identify either primary root cause or key symptoms."

        # -------------------------------------------------------------
        # 2. Evidence Grounding & Citations
        # -------------------------------------------------------------
        all_cited_supporting: List[str] = []
        all_cited_contradicting: List[str] = []
        for h in output.hypotheses:
            all_cited_supporting.extend(h.supporting_evidence)
            all_cited_contradicting.extend(h.contradicting_evidence)

        all_citations = all_cited_supporting + all_cited_contradicting
        total_citations = len(all_citations)
        unique_citations = set(all_citations)

        valid_citations = [cid for cid in all_citations if cid in valid_ev_ids]
        invalid_citations = [cid for cid in all_citations if cid not in valid_ev_ids]

        valid_count = len(valid_citations)
        invalid_count = len(invalid_citations)
        citation_validity_rate = 1.0 if total_citations == 0 else (valid_count / total_citations)

        # Essential recall
        essential_set = set(gt.essential_evidence_ids)
        cited_supporting_set = set(all_cited_supporting)
        essential_cited = sorted(list(essential_set.intersection(cited_supporting_set)))
        essential_missing = sorted(list(essential_set - cited_supporting_set))

        if essential_set:
            essential_recall = len(essential_cited) / len(essential_set)
        else:
            essential_recall = 1.0

        # Irrelevant citations (noise)
        irrelevant_set = set(gt.irrelevant_evidence_ids)
        irrelevant_cited = sorted(list(irrelevant_set.intersection(unique_citations)))

        # Evidence precision
        if total_citations > 0:
            relevant_citations_count = total_citations - len(irrelevant_cited) - invalid_count
            evidence_precision = max(0.0, min(1.0, relevant_citations_count / total_citations))
        else:
            evidence_precision = 1.0 if not essential_set else 0.0

        grounding_score = round(
            (0.4 * citation_validity_rate) + (0.4 * essential_recall) + (0.2 * evidence_precision),
            4,
        )

        # -------------------------------------------------------------
        # 3. Uncertainty & Hallucinations
        # -------------------------------------------------------------
        unsupported_claims = 0
        hallucination_detected = False
        unc_notes = []

        for h in output.hypotheses:
            # Check for fabricated citations
            for cid in h.supporting_evidence:
                if cid not in valid_ev_ids:
                    unsupported_claims += 1
                    hallucination_detected = True
                    unc_notes.append(f"Hypothesis {h.id} cited fabricated evidence ID '{cid}'.")

            # Check for unsupported claims marked "supported"
            if h.status == "supported":
                if not gt.true_cause_identifiable:
                    unsupported_claims += 1
                    hallucination_detected = True
                    unc_notes.append(f"Hypothesis {h.id} claimed 'supported' when true cause is unidentifiable.")
                elif not any(cid in essential_set for cid in h.supporting_evidence):
                    unsupported_claims += 1
                    unc_notes.append(f"Hypothesis {h.id} marked 'supported' without citing any essential evidence.")

        unsupported_claim_rate = unsupported_claims / max(1, len(output.hypotheses))

        # Scenario-specific uncertainty score
        if not gt.true_cause_identifiable:
            if any(h.status == "supported" for h in output.hypotheses):
                uncertainty_score = 0.0
                unc_notes.append("Penalized for declaring supported status on unidentifiable scenario.")
            else:
                has_missing_ev = any(len(h.missing_evidence) > 0 for h in output.hypotheses)
                uncertainty_score = 1.0 if has_missing_ev else 0.7
                unc_notes.append("Correctly handled uncertainty on unidentifiable scenario.")
        elif scenario.category == ScenarioCategory.CONTRADICTORY_EVIDENCE:
            # Did it recognize contradictory metric or avoid declaring contradicted lead supported?
            contra_cited = any(cid in gt.contradicting_evidence_ids for cid in all_cited_contradicting)
            deadlock_claimed_supported = any(
                "deadlock" in h.description.lower() and h.status == "supported" for h in output.hypotheses
            )
            if deadlock_claimed_supported:
                uncertainty_score = 0.2
                unc_notes.append("False lead (database deadlock) was asserted as supported despite zero deadlocks metric.")
            elif contra_cited or primary_matches:
                uncertainty_score = 1.0
                unc_notes.append("Contradicted lead properly identified or discarded in favor of gateway rate limit.")
            else:
                uncertainty_score = 0.6
        elif scenario.category == ScenarioCategory.AMBIGUOUS_EVIDENCE:
            if len(output.hypotheses) >= 2 or any(h.status in ("possible", "inconclusive") for h in output.hypotheses):
                uncertainty_score = 1.0
                unc_notes.append("Multiple competing possibilities acknowledged in ambiguous scenario.")
            else:
                uncertainty_score = 0.5
                unc_notes.append("Single explanation asserted with insufficient ambiguity handling.")
        else:
            # Standard root cause known
            if diagnosis_status == "identified" and any(h.status == "supported" for h in output.hypotheses):
                uncertainty_score = 1.0
                unc_notes.append("Correct high-confidence grounded hypothesis.")
            elif diagnosis_status == "identified":
                uncertainty_score = 0.8
                unc_notes.append("Correct root cause identified with conservative status.")
            else:
                uncertainty_score = 0.4
                unc_notes.append("Failed to establish grounded hypothesis for known root cause.")

        # -------------------------------------------------------------
        # 4. Actionability & Diagnostic Quality
        # -------------------------------------------------------------
        next_steps_text = " ".join([h.next_step.lower() for h in output.hypotheses])
        matched_action_kws = [kw for kw in gt.action_keywords if kw.lower() in next_steps_text]

        if gt.action_keywords:
            action_alignment_score = min(1.0, len(matched_action_kws) / min(3, len(gt.action_keywords)))
        else:
            action_alignment_score = 1.0

        # Check for concrete markers
        matched_markers = [m for m in cls.SPECIFICITY_MARKERS if m in next_steps_text]
        if len(matched_markers) >= 2:
            action_specificity_score = 1.0
        elif len(matched_markers) == 1:
            action_specificity_score = 0.7
        else:
            # Generic action text like "check logs"
            action_specificity_score = 0.3

        actionability_score = round(
            (0.6 * action_alignment_score) + (0.4 * action_specificity_score),
            4,
        )

        # -------------------------------------------------------------
        # 5. Composite Score & Review Triggers
        # -------------------------------------------------------------
        composite_score = round(
            (0.35 * diagnosis_accuracy_score)
            + (0.25 * grounding_score)
            + (0.25 * uncertainty_score)
            + (0.15 * actionability_score),
            4,
        )

        human_review = (
            composite_score < 0.70
            or hallucination_detected
            or scenario.category in (ScenarioCategory.AMBIGUOUS_EVIDENCE, ScenarioCategory.CONTRADICTORY_EVIDENCE)
        )

        qualitative_notes = "; ".join(unc_notes) if unc_notes else "Clean grounded investigation."

        return ScenarioEvaluationResult(
            scenario_id=scenario.id,
            scenario_name=scenario.name,
            category=scenario.category,
            diagnosis_status=diagnosis_status,
            diagnosis_accuracy_score=diagnosis_accuracy_score,
            identified_root_cause_vs_symptom=identified_rc,
            diagnosis_explanation=diag_expl,
            total_citations=total_citations,
            valid_citations_count=valid_count,
            invalid_citations_count=invalid_count,
            citation_validity_rate=round(citation_validity_rate, 4),
            essential_evidence_cited=essential_cited,
            essential_evidence_missing=essential_missing,
            essential_evidence_recall=round(essential_recall, 4),
            irrelevant_evidence_cited=irrelevant_cited,
            evidence_precision=round(evidence_precision, 4),
            grounding_score=grounding_score,
            unsupported_claims_count=unsupported_claims,
            unsupported_claim_rate=round(unsupported_claim_rate, 4),
            uncertainty_score=round(uncertainty_score, 4),
            hallucination_detected=hallucination_detected,
            uncertainty_explanation=qualitative_notes,
            matched_action_keywords=matched_action_kws,
            action_alignment_score=round(action_alignment_score, 4),
            action_specificity_score=round(action_specificity_score, 4),
            actionability_score=actionability_score,
            composite_score=composite_score,
            human_review_required=human_review,
            qualitative_notes=qualitative_notes,
        )

    @classmethod
    def aggregate_results(
        cls,
        results: List[ScenarioEvaluationResult],
    ) -> AggregateEvaluationMetrics:
        if not results:
            return AggregateEvaluationMetrics(
                total_scenarios=0,
                evaluated_scenarios=0,
                average_diagnosis_accuracy=0.0,
                root_cause_identification_rate=0.0,
                average_citation_validity=0.0,
                average_evidence_recall=0.0,
                average_evidence_precision=0.0,
                average_unsupported_claim_rate=0.0,
                average_uncertainty_score=0.0,
                average_actionability_score=0.0,
                overall_benchmark_score=0.0,
                scenarios_requiring_human_review=0,
            )

        n = len(results)
        return AggregateEvaluationMetrics(
            total_scenarios=n,
            evaluated_scenarios=n,
            average_diagnosis_accuracy=round(sum(r.diagnosis_accuracy_score for r in results) / n, 4),
            root_cause_identification_rate=round(sum(1.0 for r in results if r.identified_root_cause_vs_symptom) / n, 4),
            average_citation_validity=round(sum(r.citation_validity_rate for r in results) / n, 4),
            average_evidence_recall=round(sum(r.essential_evidence_recall for r in results) / n, 4),
            average_evidence_precision=round(sum(r.evidence_precision for r in results) / n, 4),
            average_unsupported_claim_rate=round(sum(r.unsupported_claim_rate for r in results) / n, 4),
            average_uncertainty_score=round(sum(r.uncertainty_score for r in results) / n, 4),
            average_actionability_score=round(sum(r.actionability_score for r in results) / n, 4),
            overall_benchmark_score=round(sum(r.composite_score for r in results) / n, 4),
            scenarios_requiring_human_review=sum(1 for r in results if r.human_review_required),
        )

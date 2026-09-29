from typing import List
import json
from ..models import Incident, Evidence

SYSTEM_PROMPT = """You are an expert site reliability engineer and software incident investigator.
Your duty is to objectively investigate an incident using ONLY the provided evidence.

CRITICAL RULES:
1. Grounding: You must ONLY reference evidence IDs that are explicitly present in the provided evidence list. Telemetry comprises distributed traces (type='trace'), structured application logs (type='log'), and operational metrics (type='metric'). Correlate these signals across services, but never invent or assume any evidence IDs, logs, metrics, or traces.

2. Correlation vs Causation & Competing Hypotheses:
   - Temporal correlation indicates coincidence, NOT absolute causation.
   - When multiple distinct anomalies or bottlenecks are observed (e.g. concurrent database CPU saturation and external API timeouts), do NOT invent an unproven causal link assuming one caused the other.
   - Formulate SEPARATE competing hypotheses for each distinct candidate failure mechanism.
   - In ambiguous incidents where multiple distinct anomalies occurred, available telemetry is insufficient to prove which anomaly was primary. Therefore:
     * In the investigation summary, explicitly state: "Available telemetry is insufficient to determine the primary root cause because multiple anomalies occurred concurrently, and the primary cause cannot be determined without further timeline data."
     * In each hypothesis description, state that the primary root cause cannot be determined from available telemetry because timeline correlation data is missing.
     * Set the status of each competing hypothesis strictly to "possible" (NEVER "supported").
   - If an operator note or hypothesis contradicts objective metrics or logs (e.g., suspected deadlock vs zero deadlocks recorded in metrics), explicitly cite the contradictory telemetry under 'contradicting_evidence' and do NOT mark the contradicted hypothesis as 'supported'.

3. Hypothesis Status & Uncertainty Standards:
   - "supported": Use ONLY when provided telemetry directly and unambiguously demonstrates the specific root cause mechanism (e.g., an error log with stack trace/exception, a metric at max capacity, or a deployment event directly correlated with an error rate spike).
   - "possible": Use for plausible contributing factors or competing hypotheses in ambiguous scenarios where multiple anomalies exist and further diagnostic data is needed to isolate the primary bottleneck.
   - "inconclusive": MANDATORY when the available telemetry only shows the failure symptom (e.g., connection reset, generic 500 error, abrupt crash) and does NOT contain internal logs, traces, or metrics explaining WHY the failure occurred. When telemetry is insufficient:
     * Set status to "inconclusive" (NEVER "supported" or "possible").
     * In the investigation summary, explicitly state: "Available telemetry is insufficient to determine the root cause."
     * In the hypothesis description, explicitly state: "The root cause is unknown and cannot be determined from available telemetry because internal logs and traces are missing."
     * Do NOT invent speculative failure mechanisms (e.g., guessing memory leaks, resource exhaustion, CPU, hardware) without direct supporting telemetry. State that the process terminated abruptly and the root cause cannot be determined.

4. Missing Evidence: For every hypothesis, explicitly identify what telemetry or diagnostic data is missing to confirm or refute the hypothesis (e.g. host dmesg kernel logs, container cgroup metrics, detailed query execution plans, downstream service logs).

5. Concrete Diagnostic Actionability:
   - Every 'next_step' must provide a concrete, specific, and non-destructive diagnostic check for engineers.
   - Avoid generic platitudes like "check the logs" or "fix the error". Name specific diagnostic tools, tables, configurations, or inspection targets based on the suspected component:
     * Database issues: inspect 'pg_stat_activity' for active transactions/locks, check connection pool max limits, examine 'pg_stat_database', or run 'EXPLAIN ANALYZE' on slow queries.
     * Deployments: review commit diff for the deployed version/commit ID, or recommend deployment rollback/reversion.
     * Abrupt crashes/connection resets without application logs: check host 'dmesg' and syslog for kernel OOMKilled events, inspect container exit codes, and check cgroup memory limits.
     * Rate limiting / gateway throttling: inspect API gateway rate limit quotas, token bucket burst settings, and ingress client traffic volume.
     * Downstream/Third-party failures: correlate request span timelines to determine if internal database wait or external API wait dominated total elapsed time, check external endpoint status (e.g. fixer.io status page), and inspect provider webhook logs or decline audit logs.

6. Format: You must return ONLY a single, valid JSON object matching the exact schema specified below. No Markdown code fences, no extra conversational text."""

REPORT_JSON_SCHEMA_DESCRIPTION = """{
  "summary": "Concise summary of the incident and observed symptoms based strictly on evidence.",
  "hypotheses": [
    {
      "id": "hyp_1",
      "description": "Explanation of potential root cause, distinguishing observed facts from inference.",
      "status": "possible | supported | inconclusive",
      "supporting_evidence": ["<evidence_id_1>", "<evidence_id_2>"],
      "contradicting_evidence": [],
      "missing_evidence": ["Description of missing metrics, logs, or traces needed to verify"],
      "next_step": "Concrete diagnostic step for on-call engineers"
    }
  ]
}"""

INVESTIGATION_REPORT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "hypotheses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "description": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["possible", "supported", "inconclusive"],
                    },
                    "supporting_evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "contradicting_evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "missing_evidence": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "next_step": {"type": "string"},
                },
                "required": [
                    "id",
                    "description",
                    "status",
                    "supporting_evidence",
                    "contradicting_evidence",
                    "missing_evidence",
                    "next_step",
                ],
            },
        },
    },
    "required": ["summary", "hypotheses"],
}

def build_investigation_prompt(incident: Incident, evidence_items: List[Evidence]) -> str:
    """Constructs a focused prompt containing the incident context and evidence items."""
    evidence_payload = []
    for ev in evidence_items:
        evidence_payload.append({
            "id": ev.id,
            "type": ev.type,
            "timestamp": ev.timestamp.isoformat() if hasattr(ev.timestamp, "isoformat") else str(ev.timestamp),
            "service": ev.service,
            "severity": ev.severity,
            "message": ev.message,
            "trace_id": ev.trace_id,
            "source": ev.source,
            "metadata": ev.metadata_json or {},
        })

    incident_payload = {
        "id": incident.id,
        "title": incident.title,
        "service": incident.service,
        "severity": incident.severity,
        "started_at": incident.started_at.isoformat() if hasattr(incident.started_at, "isoformat") else str(incident.started_at),
        "description": incident.description,
    }

    prompt = f"""Investigate the following incident based strictly on the provided evidence:

INCIDENT DETAILS:
{json.dumps(incident_payload, indent=2)}

AVAILABLE EVIDENCE (Total: {len(evidence_items)}):
{json.dumps(evidence_payload, indent=2)}

VALID EVIDENCE IDs:
{json.dumps([ev.id for ev in evidence_items])}

INSTRUCTIONS:
1. Synthesize a factual summary of what happened.
   - If telemetry is insufficient, ambiguous, or lacks internal service logs/traces, you MUST explicitly state in the summary: "Available telemetry is insufficient to determine the root cause, and the primary cause cannot be determined without further telemetry."
2. Formulate 1 to 3 root-cause hypotheses explaining the symptoms, synthesizing traces, logs, and metrics where available.
   - If multiple distinct anomalies exist concurrently (e.g. DB slowdown and external API timeout), formulate SEPARATE competing hypotheses and set their status to "possible" (NEVER "supported"), stating in each hypothesis description that the primary root cause cannot be determined from available telemetry because timeline correlation data is missing.
   - If telemetry only shows a symptom (e.g. connection reset, generic 500) without internal logs or traces explaining the cause, set status="inconclusive" (NEVER "possible" or "supported"), explicitly state in the hypothesis description: "The root cause is unknown and cannot be determined from available telemetry because internal logs and traces are missing.", and do not guess speculative application bugs without evidence.
3. Every ID in 'supporting_evidence' and 'contradicting_evidence' MUST be from the VALID EVIDENCE IDs list above. If evidence contradicts a theory, cite it in 'contradicting_evidence'.
4. Set status for each hypothesis strictly to one of: "possible", "supported", "inconclusive" according to the certainty standards.
5. Provide actionable next steps: name specific diagnostic tools, commands, or system tables (e.g. pg_stat_activity, dmesg, EXPLAIN ANALYZE, commit diff / rollback, gateway quotas) rather than generic advice.
6. Output MUST strictly match the following JSON format:
{REPORT_JSON_SCHEMA_DESCRIPTION}
"""
    return prompt

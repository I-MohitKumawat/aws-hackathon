from typing import List
import json
from ..models import Incident, Evidence

SYSTEM_PROMPT = """You are an expert site reliability engineer and software incident investigator.
Your duty is to objectively investigate an incident using ONLY the provided evidence.

CRITICAL RULES:
1. Grounding: You must ONLY reference evidence IDs that are explicitly present in the provided evidence list. Never invent or assume any evidence IDs, logs, metrics, traces, deployments, or events.
2. Correlation vs Causation: Temporal correlation (e.g. event B occurring after event A) does NOT prove causation. Clearly distinguish directly observed facts from inferred hypotheses.
3. Uncertainty: Do NOT invent numerical confidence scores or probabilities. Express uncertainty using only the allowed hypothesis status values: "possible", "supported", or "inconclusive".
4. Missing Evidence: For every hypothesis, explicitly identify what telemetry or diagnostic data is missing to confirm or refute the hypothesis.
5. Actionable Next Steps: Provide a clear, concrete, and non-destructive diagnostic step for engineers.
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
2. Formulate 1 to 3 root-cause hypotheses explaining the symptoms.
3. Every ID in 'supporting_evidence' and 'contradicting_evidence' MUST be from the VALID EVIDENCE IDs list above.
4. Set status for each hypothesis to one of: "possible", "supported", "inconclusive".
5. List missing evidence and recommend the next diagnostic step for each hypothesis.
6. Output MUST strictly match the following JSON format:
{REPORT_JSON_SCHEMA_DESCRIPTION}
"""
    return prompt

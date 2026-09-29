import json
import uuid
from typing import Set, List, Dict, Any, Tuple
from pydantic import BaseModel, Field, ValidationError

from ..schemas.report import Hypothesis, HypothesisStatus

class ReportValidationError(Exception):
    """Raised when model output fails JSON parsing, schema validation, or evidence reference integrity."""
    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}

class RawAIInvestigationOutput(BaseModel):
    summary: str
    hypotheses: List[Hypothesis] = Field(default_factory=list)

def validate_model_investigation_output(
    raw_output: str,
    valid_evidence_ids: Set[str],
) -> RawAIInvestigationOutput:
    """
    Parses and validates raw LLM JSON output:
    1. Extracts and parses JSON.
    2. Validates against Pydantic RawAIInvestigationOutput schema.
    3. Verifies that all referenced evidence IDs in hypotheses exist in valid_evidence_ids.
    4. Rejects any fabricated or unknown evidence IDs.
    """
    # 1. Parse JSON
    cleaned_output = raw_output.strip()
    # Strip potential markdown fences if present despite system instructions
    if cleaned_output.startswith("```json"):
        cleaned_output = cleaned_output[7:]
    elif cleaned_output.startswith("```"):
        cleaned_output = cleaned_output[3:]
    if cleaned_output.endswith("```"):
        cleaned_output = cleaned_output[:-3]
    cleaned_output = cleaned_output.strip()

    try:
        data = json.loads(cleaned_output)
    except json.JSONDecodeError as exc:
        raise ReportValidationError(
            f"Model output is not valid JSON: {exc.msg}",
            details={"raw_output": raw_output, "error_type": "INVALID_JSON"},
        ) from exc

    if not isinstance(data, dict):
        raise ReportValidationError(
            f"Expected a JSON object from model, but received {type(data).__name__}",
            details={"raw_output": raw_output, "error_type": "INVALID_ROOT_TYPE"},
        )

    # 2. Pydantic Schema Validation
    try:
        validated = RawAIInvestigationOutput.model_validate(data)
    except ValidationError as exc:
        raise ReportValidationError(
            f"Model output failed schema validation: {exc}",
            details={"errors": exc.errors(), "error_type": "SCHEMA_VALIDATION_ERROR"},
        ) from exc

    if not validated.summary.strip():
        raise ReportValidationError(
            "Report 'summary' must not be empty.",
            details={"error_type": "EMPTY_SUMMARY"},
        )

    if not validated.hypotheses:
        raise ReportValidationError(
            "Report must contain at least one hypothesis.",
            details={"error_type": "NO_HYPOTHESES"},
        )

    # 3. Evidence Reference Integrity Check
    for hyp in validated.hypotheses:
        referenced_ids = set(hyp.supporting_evidence + hyp.contradicting_evidence)
        invalid_ids = referenced_ids - valid_evidence_ids
        if invalid_ids:
            raise ReportValidationError(
                f"Hypothesis '{hyp.id}' references fabricated or unknown evidence ID(s): {sorted(list(invalid_ids))}",
                details={
                    "hypothesis_id": hyp.id,
                    "invalid_evidence_ids": sorted(list(invalid_ids)),
                    "valid_evidence_ids": sorted(list(valid_evidence_ids)),
                    "error_type": "INVALID_EVIDENCE_REFERENCE",
                },
            )

    return validated

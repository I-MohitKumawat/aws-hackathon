import pytest
import json
import httpx
from unittest.mock import AsyncMock, patch

from backend.app.models import Incident, Evidence
from backend.app.agent import (
    OllamaClient,
    OllamaConnectionError,
    OllamaTimeoutError,
    OllamaResponseError,
    SYSTEM_PROMPT,
    build_investigation_prompt,
    validate_model_investigation_output,
    ReportValidationError,
)
from backend.app.services.investigation_service import investigate_incident
from backend.tests.fixtures.controlled_incident import (
    CONTROLLED_INCIDENT,
    CONTROLLED_EVIDENCE,
    get_controlled_incident_models,
)

REPRESENTATIVE_MODEL_OUTPUT = json.dumps({
    "summary": "Checkout service experienced a spike in HTTP 500 errors correlated with deployment checkout-v2.1.0 and database connection pool exhaustion.",
    "hypotheses": [
        {
            "id": "hyp_01",
            "description": "Deployment checkout-v2.1.0 introduced connection leaks or unindexed queries leading to PostgreSQL connection saturation.",
            "status": "possible",
            "supporting_evidence": ["ev_dep_01", "ev_log_01", "ev_met_01", "ev_met_02"],
            "contradicting_evidence": [],
            "missing_evidence": [
                "Connection pool configuration diff in checkout-v2.1.0",
                "PostgreSQL pg_stat_activity active lock queries",
            ],
            "next_step": "Inspect database connection pool settings and slow query logs for checkout-v2.1.0.",
        }
    ]
})

def test_controlled_incident_fixture():
    incident, evidence_items = get_controlled_incident_models()
    assert incident.id == "inc_checkout_500"
    assert incident.service == "checkout"
    assert len(evidence_items) == 4
    ids = {ev.id for ev in evidence_items}
    assert ids == {"ev_dep_01", "ev_log_01", "ev_met_01", "ev_met_02"}

def test_build_investigation_prompt():
    incident, evidence_items = get_controlled_incident_models()
    prompt = build_investigation_prompt(incident, evidence_items)

    assert "inc_checkout_500" in prompt
    assert "ev_dep_01" in prompt
    assert "ev_log_01" in prompt
    assert "ev_met_01" in prompt
    assert "ev_met_02" in prompt
    assert "VALID EVIDENCE IDs" in prompt

def test_validator_successful_parsing():
    valid_ids = {"ev_dep_01", "ev_log_01", "ev_met_01", "ev_met_02"}
    output = validate_model_investigation_output(REPRESENTATIVE_MODEL_OUTPUT, valid_ids)

    assert output.summary.startswith("Checkout service experienced")
    assert len(output.hypotheses) == 1
    hyp = output.hypotheses[0]
    assert hyp.id == "hyp_01"
    assert hyp.status == "possible"
    assert set(hyp.supporting_evidence) == valid_ids
    assert len(hyp.missing_evidence) == 2
    assert "connection pool settings" in hyp.next_step

def test_validator_strips_markdown_fences():
    valid_ids = {"ev_dep_01", "ev_log_01", "ev_met_01", "ev_met_02"}
    fenced_output = f"```json\n{REPRESENTATIVE_MODEL_OUTPUT}\n```"
    output = validate_model_investigation_output(fenced_output, valid_ids)
    assert len(output.hypotheses) == 1

def test_validator_rejects_invalid_json():
    valid_ids = {"ev_dep_01"}
    bad_json = "{ summary: unquoted }"
    with pytest.raises(ReportValidationError) as exc_info:
        validate_model_investigation_output(bad_json, valid_ids)
    assert "not valid JSON" in str(exc_info.value)
    assert exc_info.value.details["error_type"] == "INVALID_JSON"

def test_validator_rejects_invalid_root_type():
    valid_ids = {"ev_dep_01"}
    bad_root = json.dumps(["an", "array"])
    with pytest.raises(ReportValidationError) as exc_info:
        validate_model_investigation_output(bad_root, valid_ids)
    assert "Expected a JSON object" in str(exc_info.value)

def test_validator_rejects_missing_required_fields():
    valid_ids = {"ev_dep_01"}
    # Missing 'next_step' and 'description'
    incomplete = json.dumps({
        "summary": "Something failed.",
        "hypotheses": [
            {
                "id": "hyp_1",
                "status": "possible",
                "supporting_evidence": ["ev_dep_01"],
            }
        ]
    })
    with pytest.raises(ReportValidationError) as exc_info:
        validate_model_investigation_output(incomplete, valid_ids)
    assert "failed schema validation" in str(exc_info.value)

def test_validator_rejects_empty_summary():
    valid_ids = {"ev_dep_01"}
    empty_summary = json.dumps({
        "summary": "   ",
        "hypotheses": [
            {
                "id": "hyp_1",
                "description": "Desc",
                "status": "possible",
                "supporting_evidence": ["ev_dep_01"],
                "next_step": "Step",
            }
        ]
    })
    with pytest.raises(ReportValidationError) as exc_info:
        validate_model_investigation_output(empty_summary, valid_ids)
    assert "summary' must not be empty" in str(exc_info.value)

def test_validator_rejects_fabricated_evidence_id():
    valid_ids = {"ev_dep_01", "ev_log_01"}
    fabricated_output = json.dumps({
        "summary": "Suspected network partition.",
        "hypotheses": [
            {
                "id": "hyp_01",
                "description": "Database connection timed out.",
                "status": "possible",
                "supporting_evidence": ["ev_dep_01", "ev_fabricated_999"],
                "contradicting_evidence": [],
                "missing_evidence": [],
                "next_step": "Inspect routing table.",
            }
        ]
    })
    with pytest.raises(ReportValidationError) as exc_info:
        validate_model_investigation_output(fabricated_output, valid_ids)
    assert "fabricated or unknown evidence ID" in str(exc_info.value)
    assert "ev_fabricated_999" in str(exc_info.value)

@pytest.mark.asyncio
async def test_ollama_client_success():
    mock_transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"response": REPRESENTATIVE_MODEL_OUTPUT})
    )
    async with httpx.AsyncClient(transport=mock_transport) as client:
        ollama = OllamaClient(http_client=client)
        resp = await ollama.generate("Test prompt")
        assert resp == REPRESENTATIVE_MODEL_OUTPUT

@pytest.mark.asyncio
async def test_ollama_client_connection_error():
    async def handler(request):
        raise httpx.ConnectError("Connection refused")

    mock_transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=mock_transport) as client:
        ollama = OllamaClient(http_client=client)
        with pytest.raises(OllamaConnectionError) as exc_info:
            await ollama.generate("Test prompt")
        assert "Failed to connect to Ollama" in str(exc_info.value)

@pytest.mark.asyncio
async def test_ollama_client_timeout():
    async def handler(request):
        raise httpx.TimeoutException("Read timed out")

    mock_transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=mock_transport) as client:
        ollama = OllamaClient(http_client=client)
        with pytest.raises(OllamaTimeoutError) as exc_info:
            await ollama.generate("Test prompt")
        assert "timed out after" in str(exc_info.value)

@pytest.mark.asyncio
async def test_ollama_client_http_error():
    mock_transport = httpx.MockTransport(
        lambda request: httpx.Response(500, text="Internal Server Error")
    )
    async with httpx.AsyncClient(transport=mock_transport) as client:
        ollama = OllamaClient(http_client=client)
        with pytest.raises(OllamaResponseError) as exc_info:
            await ollama.generate("Test prompt")
        assert exc_info.value.status_code == 500

@pytest.mark.asyncio
async def test_investigate_incident_end_to_end_mock():
    incident, evidence_items = get_controlled_incident_models()
    mock_client = AsyncMock(spec=OllamaClient)
    mock_client.generate.return_value = REPRESENTATIVE_MODEL_OUTPUT

    result = await investigate_incident(
        incident=incident,
        evidence_items=evidence_items,
        client=mock_client,
    )
    assert len(result.hypotheses) == 1
    assert result.hypotheses[0].id == "hyp_01"
    mock_client.generate.assert_called_once()

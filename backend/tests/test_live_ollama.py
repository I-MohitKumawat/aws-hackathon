import os
import pytest
from backend.app.agent import OllamaClient
from backend.app.services.investigation_service import investigate_incident
from backend.tests.fixtures.controlled_incident import get_controlled_incident_models

@pytest.mark.asyncio
async def test_live_ollama_investigation():
    """
    Opt-in live integration test that runs against a live local Ollama instance.
    To execute: RUN_LIVE_OLLAMA=true pytest backend/tests/test_live_ollama.py
    """
    if os.environ.get("RUN_LIVE_OLLAMA", "").lower() != "true":
        pytest.skip("Skipping live Ollama test. Set RUN_LIVE_OLLAMA=true to run against live local Ollama.")

    incident, evidence_items = get_controlled_incident_models()
    client = OllamaClient()

    result = await investigate_incident(
        incident=incident,
        evidence_items=evidence_items,
        client=client,
    )

    assert result.summary
    assert len(result.hypotheses) >= 1
    valid_ids = {ev.id for ev in evidence_items}
    for hyp in result.hypotheses:
        assert hyp.status in ["possible", "supported", "inconclusive"]
        for ev_id in hyp.supporting_evidence:
            assert ev_id in valid_ids
        for ev_id in hyp.contradicting_evidence:
            assert ev_id in valid_ids

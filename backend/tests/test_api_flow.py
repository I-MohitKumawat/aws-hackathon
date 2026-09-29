import time
import json
import re
from unittest.mock import patch
from backend.app.agent import OllamaClient

async def mock_ollama_generate(self, prompt, system=None, options=None, **kwargs):
    match = re.search(r"VALID EVIDENCE IDs:\s*(\[[^\]]+\])", prompt)
    ev_ids = json.loads(match.group(1)) if match else []
    return json.dumps({
        "summary": "Checkout requests experienced database connection timeouts.",
        "hypotheses": [
            {
                "id": "hyp_01",
                "description": "A recent deployment may have caused connection pool exhaustion.",
                "status": "possible",
                "supporting_evidence": ev_ids,
                "contradicting_evidence": [],
                "missing_evidence": ["Database connection pool metrics"],
                "next_step": "Inspect connection pool usage around the deployment.",
            }
        ]
    })

def test_full_api_investigation_lifecycle(client):
    with patch.object(OllamaClient, "generate", new=mock_ollama_generate):
        # 1. Create Incident
        create_payload = {
            "title": "Checkout service timeout",
            "service": "checkout",
            "severity": "high",
            "started_at": "2026-09-29T09:30:00Z",
            "description": "Checkout requests are timing out.",
        }
        res = client.post("/api/v1/incidents", json=create_payload)
        assert res.status_code == 201, res.text
        incident = res.json()
        incident_id = incident["id"]
        assert incident["status"] == "open"
        assert incident["service"] == "checkout"

        # 2. List Incidents
        res = client.get("/api/v1/incidents")
        assert res.status_code == 200
        list_data = res.json()
        assert list_data["total"] >= 1
        assert any(i["id"] == incident_id for i in list_data["items"])

        # 3. Get Incident Details
        res = client.get(f"/api/v1/incidents/{incident_id}")
        assert res.status_code == 200
        assert res.json()["title"] == "Checkout service timeout"

        # 4. Ingest Telemetry
        telemetry_payload = {
            "incident_id": incident_id,
            "evidence": [
                {
                    "type": "log",
                    "timestamp": "2026-09-29T09:32:10Z",
                    "service": "checkout",
                    "severity": "error",
                    "message": "Database connection timeout",
                    "trace_id": "trace_abc123",
                    "metadata": {},
                },
                {
                    "type": "deployment",
                    "timestamp": "2026-09-29T09:25:00Z",
                    "service": "checkout",
                    "severity": "info",
                    "message": "Deployment checkout-v2",
                    "metadata": {"version": "v2"},
                },
            ],
        }
        res = client.post("/api/v1/telemetry", json=telemetry_payload)
        assert res.status_code == 202
        assert res.json()["accepted_count"] == 2

        # 5. List Evidence
        res = client.get(f"/api/v1/incidents/{incident_id}/evidence")
        assert res.status_code == 200
        ev_data = res.json()
        assert ev_data["total"] == 2
        assert ev_data["items"][0]["service"] == "checkout"

        # 6. Start Investigation
        start_payload = {
            "time_window": {
                "start": "2026-09-29T09:20:00Z",
                "end": "2026-09-29T09:40:00Z",
            }
        }
        res = client.post(f"/api/v1/incidents/{incident_id}/investigations", json=start_payload)
        assert res.status_code == 202
        job_data = res.json()
        job_id = job_data["job_id"]
        assert job_data["incident_id"] == incident_id

        # 7. Check Progress / Wait for background task to complete
        for _ in range(20):
            res = client.get(f"/api/v1/investigations/{job_id}")
            assert res.status_code == 200
            status_data = res.json()
            if status_data["status"] == "completed":
                break
            time.sleep(0.2)

        assert status_data["status"] == "completed"

        # 8. Retrieve Report
        res = client.get(f"/api/v1/investigations/{job_id}/report")
        assert res.status_code == 200
        report = res.json()
        assert report["incident_id"] == incident_id
        assert report["status"] == "completed"
        assert len(report["hypotheses"]) > 0
        assert report["hypotheses"][0]["status"] in ["possible", "supported"]

        # 9. Update Incident Status
        patch_payload = {
            "status": "resolved",
            "ended_at": "2026-09-29T10:00:00Z",
        }
        res = client.patch(f"/api/v1/incidents/{incident_id}", json=patch_payload)
        assert res.status_code == 200
        assert res.json()["status"] == "resolved"

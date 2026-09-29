def test_health_check(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "environment" in data

def test_services_health_check(client):
    response = client.get("/api/v1/health/services")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "services" in data
    assert "postgres" in data["services"]

def test_global_evidence_search(client):
    response = client.get("/api/v1/evidence?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert "items" in data
    assert "total" in data


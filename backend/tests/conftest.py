import pytest
from fastapi.testclient import TestClient
from backend.app.main import app

@pytest.fixture
def client():
    with TestClient(app, headers={"X-API-Key": "dev-admin-key"}) as c:
        yield c

import pytest
from fastapi.testclient import TestClient
from app.fast_api_app import app


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_root_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200


def test_start_and_stop_pipeline(client):
    response = client.post("/api/pipeline/start", json={
        "prompt": "Test prompt for server e2e",
        "num_shots": 2,
        "mode": "i2v_chaining"
    })
    assert response.status_code == 200
    data = response.json()
    assert "session_id" in data
    session_id = data["session_id"]

    # Check session status
    status_resp = client.get(f"/api/pipeline/session/{session_id}")
    assert status_resp.status_code == 200
    assert status_resp.json()["session_id"] == session_id

    # Stop pipeline
    stop_resp = client.post(f"/api/pipeline/stop/{session_id}")
    assert stop_resp.status_code == 200
    assert stop_resp.json()["status"] == "stopped"


def test_runs_endpoint(client):
    response = client.get("/api/runs")
    assert response.status_code == 200
    assert "runs" in response.json()

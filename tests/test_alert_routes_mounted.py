from fastapi.testclient import TestClient

from app.main import app


def test_alert_summary_route_is_mounted():
    response = TestClient(app).get("/alerts/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["agent_type"] == "manager-agent"
    assert "total" in body["data"]
    assert "counts" in body["data"]

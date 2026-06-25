from fastapi.testclient import TestClient

from app.main_modular import app


def test_operational_summary_route_is_mounted_on_modular_app():
    response = TestClient(app).get("/alerts/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["agent_type"] == "manager-agent"
    assert "total" in body["data"]
    assert "counts" in body["data"]

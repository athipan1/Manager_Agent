from fastapi.testclient import TestClient

from app.app_factory import create_app


client = TestClient(
    create_app(
        include_single_analysis=False,
        include_multi_analysis=False,
        include_discovery=False,
        include_scanner=False,
        include_system=False,
        include_trade_replay=False,
        include_alpha_agents=True,
    )
)


def test_alpha_advisory_disabled_by_default():
    response = client.post("/alpha/advisory", json={})
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["advisory_only"] is True
    assert payload["data"]["enabled"] is False
    assert "market_regime" in payload["data"]["skipped"]


def test_alpha_health_disabled_by_default():
    response = client.get("/alpha/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["enabled"] is False
    assert payload["data"]["services"]["portfolio"]["status"] == "disabled"

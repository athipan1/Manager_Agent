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


def test_alpha_market_strategy_route(monkeypatch):
    async def fake_recommend_market_strategy(payload, correlation_id):
        return {
            "enabled": True,
            "recommendation": {
                "symbol": payload["symbol"],
                "regime": "bull",
                "recommended_strategy": "trend_following",
                "position_size_multiplier": 1.0,
            },
        }

    monkeypatch.setattr("app.routes.alpha_agents.recommend_market_strategy", fake_recommend_market_strategy)

    response = client.post(
        "/alpha/market-strategy",
        json={
            "symbol": "SPY",
            "price": 550,
            "sma_50": 530,
            "sma_200": 500,
            "atr_pct": 0.015,
            "vix": 15,
            "market_breadth_pct": 0.70,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["enabled"] is True
    assert payload["data"]["recommendation"]["recommended_strategy"] == "trend_following"
    assert payload["data"]["recommendation"]["position_size_multiplier"] == 1.0


def test_alpha_market_strategy_route_returns_error_payload(monkeypatch):
    async def fake_recommend_market_strategy(payload, correlation_id):
        raise RuntimeError("market regime unavailable")

    monkeypatch.setattr("app.routes.alpha_agents.recommend_market_strategy", fake_recommend_market_strategy)

    response = client.post("/alpha/market-strategy", json={"symbol": "SPY"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["data"]["recommendation"] is None
    assert "market_strategy" in payload["error"]

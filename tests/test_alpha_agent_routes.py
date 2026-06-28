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


def test_alpha_regime_backtest_plan_route(monkeypatch):
    async def fake_recommend_market_strategy(payload, correlation_id):
        return {
            "enabled": True,
            "recommendation": {
                "symbol": payload["symbol"],
                "regime": "bull",
                "recommended_strategy": "trend_following",
                "position_size_multiplier": 0.5,
            },
        }

    monkeypatch.setattr("app.routes.alpha_agents.recommend_market_strategy", fake_recommend_market_strategy)

    response = client.post(
        "/alpha/regime-backtest-plan",
        json={
            "market_regime": {"symbol": "SPY", "price": 550, "sma_50": 530, "sma_200": 500},
            "backtest": {
                "symbols": ["AAPL"],
                "initial_equity": 100000,
                "strategy": "sma_crossover",
                "fast_window": 2,
                "slow_window": 3,
                "risk_per_trade": 0.01,
                "max_position_pct": 0.10,
                "fee_bps": 1,
                "slippage_bps": 1,
                "use_risk_agent": True,
                "bars": {"AAPL": []},
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    plan = payload["data"]["plan"]
    assert plan["action"] == "compare"
    assert plan["backtest_compare_payload"]["max_position_pct"] == 0.05
    assert plan["backtest_compare_payload"]["candidates"][0]["strategy"] == "trend_following"


def test_alpha_regime_backtest_compare_route(monkeypatch):
    async def fake_recommend_market_strategy(payload, correlation_id):
        return {
            "enabled": True,
            "recommendation": {
                "symbol": payload["symbol"],
                "regime": "bull",
                "recommended_strategy": "trend_following",
                "position_size_multiplier": 0.5,
            },
        }

    async def fake_run_regime_backtest_compare(*, market_strategy, backtest_payload, correlation_id):
        return {
            "action": "compare",
            "market_strategy": market_strategy,
            "plan": {
                "action": "compare",
                "backtest_compare_payload": {
                    "symbols": backtest_payload["symbols"],
                    "max_position_pct": 0.05,
                    "candidates": [{"strategy": "trend_following"}],
                },
            },
            "compare_result": {
                "ranked_results": [{"rank": 1, "strategy": "trend_following"}],
                "best": {"strategy": "trend_following"},
            },
        }

    monkeypatch.setattr("app.routes.alpha_agents.recommend_market_strategy", fake_recommend_market_strategy)
    monkeypatch.setattr("app.routes.alpha_agents.run_regime_backtest_compare", fake_run_regime_backtest_compare)

    response = client.post(
        "/alpha/regime-backtest-compare",
        json={
            "market_regime": {"symbol": "SPY", "price": 550, "sma_50": 530, "sma_200": 500},
            "backtest": {
                "symbols": ["AAPL"],
                "initial_equity": 100000,
                "max_position_pct": 0.10,
                "bars": {"AAPL": []},
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["data"]["action"] == "compare"
    assert payload["data"]["compare_result"]["best"]["strategy"] == "trend_following"

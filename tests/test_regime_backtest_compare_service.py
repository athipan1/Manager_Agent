import pytest

from app.regime_backtest_compare_service import run_regime_backtest_compare


@pytest.mark.asyncio
async def test_run_regime_backtest_compare_executes_compare(monkeypatch):
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

    calls = []

    class FakeBacktestClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def compare_strategies(self, payload, correlation_id):
            calls.append((payload, correlation_id))
            return {
                "ranked_results": [{"strategy": "trend_following", "score": 1.0}],
                "best": {"strategy": "trend_following"},
            }

    monkeypatch.setattr("app.regime_backtest_compare_service.recommend_market_strategy", fake_recommend_market_strategy)
    monkeypatch.setattr("app.regime_backtest_compare_service.BacktestAgentClient", FakeBacktestClient)

    payload = {
        "market_regime": {"symbol": "SPY"},
        "backtest": {
            "symbols": ["AAPL"],
            "initial_equity": 100000,
            "strategy": "sma_crossover",
            "fast_window": 2,
            "slow_window": 3,
            "max_position_pct": 0.10,
            "bars": {"AAPL": []},
        },
    }

    result = await run_regime_backtest_compare(payload, "cid-1")

    assert result["executed"] is True
    assert result["plan"]["action"] == "compare"
    assert result["backtest_compare"]["best"]["strategy"] == "trend_following"
    assert calls[0][1] == "cid-1"
    assert calls[0][0]["candidates"][0]["strategy"] == "trend_following"


@pytest.mark.asyncio
async def test_run_regime_backtest_compare_skips_no_trade(monkeypatch):
    async def fake_recommend_market_strategy(payload, correlation_id):
        return {
            "enabled": True,
            "recommendation": {
                "symbol": payload["symbol"],
                "regime": "volatile",
                "recommended_strategy": "no_trade",
                "position_size_multiplier": 0.0,
            },
        }

    class FakeBacktestClient:
        async def __aenter__(self):
            raise AssertionError("BacktestAgentClient should not be used for no_trade plans")

    monkeypatch.setattr("app.regime_backtest_compare_service.recommend_market_strategy", fake_recommend_market_strategy)
    monkeypatch.setattr("app.regime_backtest_compare_service.BacktestAgentClient", FakeBacktestClient)

    payload = {
        "market_regime": {"symbol": "SPY"},
        "backtest": {"symbols": ["AAPL"]},
    }

    result = await run_regime_backtest_compare(payload, "cid-2")

    assert result["executed"] is False
    assert result["plan"]["action"] == "no_trade"
    assert result["backtest_compare"] is None

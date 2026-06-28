import pytest

from app.regime_backtest_compare_service import run_regime_backtest_compare


class FakeBacktestClient:
    def __init__(self):
        self.calls = []

    async def compare_strategies(self, payload, correlation_id):
        self.calls.append((payload, correlation_id))
        return {
            "ranked_results": [
                {"rank": 1, "strategy": payload["candidates"][0]["strategy"], "score": 1.0}
            ],
            "best": {"strategy": payload["candidates"][0]["strategy"]},
        }


@pytest.mark.asyncio
async def test_run_regime_backtest_compare_calls_backtest_client():
    client = FakeBacktestClient()
    market_strategy = {
        "enabled": True,
        "recommendation": {
            "symbol": "SPY",
            "regime": "bull",
            "recommended_strategy": "trend_following",
            "position_size_multiplier": 0.5,
        },
    }
    backtest_payload = {
        "symbols": ["AAPL"],
        "initial_equity": 100000,
        "strategy": "sma_crossover",
        "fast_window": 2,
        "slow_window": 3,
        "max_position_pct": 0.10,
        "bars": {"AAPL": []},
    }

    result = await run_regime_backtest_compare(
        market_strategy=market_strategy,
        backtest_payload=backtest_payload,
        correlation_id="cid-1",
        backtest_client=client,
    )

    assert result["action"] == "compare"
    assert result["plan"]["backtest_compare_payload"]["max_position_pct"] == 0.05
    assert result["compare_result"]["best"]["strategy"] == "trend_following"
    assert client.calls[0][1] == "cid-1"
    assert client.calls[0][0]["candidates"][0]["strategy"] == "trend_following"


@pytest.mark.asyncio
async def test_run_regime_backtest_compare_skips_backtest_for_no_trade():
    client = FakeBacktestClient()
    market_strategy = {
        "enabled": True,
        "recommendation": {
            "symbol": "SPY",
            "regime": "volatile",
            "recommended_strategy": "no_trade",
            "position_size_multiplier": 0.0,
        },
    }

    result = await run_regime_backtest_compare(
        market_strategy=market_strategy,
        backtest_payload={"symbols": ["AAPL"]},
        correlation_id="cid-2",
        backtest_client=client,
    )

    assert result["action"] == "no_trade"
    assert result["compare_result"] is None
    assert client.calls == []

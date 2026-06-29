from app.regime_backtest_planner import build_compare_candidates, build_regime_backtest_plan


def test_build_compare_candidates_puts_recommended_strategy_first():
    candidates = build_compare_candidates("trend_following", fast_window=5, slow_window=20)

    assert candidates[0] == {
        "name": "trend_following",
        "strategy": "trend_following",
        "fast_window": 5,
        "slow_window": 20,
    }
    assert {candidate["strategy"] for candidate in candidates} == {
        "sma_crossover",
        "trend_following",
        "mean_reversion",
        "breakout",
    }


def test_build_compare_candidates_respects_allowed_strategies():
    candidates = build_compare_candidates(
        "trend_following",
        fast_window=5,
        slow_window=20,
        allowed_strategies=["trend_following", "breakout"],
    )

    assert [candidate["strategy"] for candidate in candidates] == ["trend_following", "breakout"]


def test_build_regime_backtest_plan_creates_compare_payload():
    recommendation = {
        "symbol": "SPY",
        "regime": "bull",
        "recommended_strategy": "trend_following",
        "position_size_multiplier": 0.5,
        "reason": "bull regime favors trend-following setups",
    }
    backtest_payload = {
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
    }

    plan = build_regime_backtest_plan(recommendation, backtest_payload)

    assert plan["action"] == "compare"
    assert plan["recommendation"] == recommendation
    compare_payload = plan["backtest_compare_payload"]
    assert compare_payload["max_position_pct"] == 0.05
    assert compare_payload["market_context"]["effective_size_multiplier"] == 0.5
    assert compare_payload["candidates"][0]["strategy"] == "trend_following"
    assert "strategy" not in compare_payload
    assert "fast_window" not in compare_payload
    assert "slow_window" not in compare_payload


def test_build_regime_backtest_plan_applies_market_context_limits():
    recommendation = {
        "symbol": "SPY",
        "regime": "bull",
        "recommended_strategy": "trend_following",
        "position_size_multiplier": 1.0,
        "risk_budget_multiplier": 0.6,
        "exposure_cap": 0.4,
        "allowed_strategies": ["trend_following", "breakout"],
        "blocked_strategies": ["mean_reversion"],
        "decision_notes": ["reduced exposure"],
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

    plan = build_regime_backtest_plan(recommendation, backtest_payload)

    assert plan["action"] == "compare"
    compare_payload = plan["backtest_compare_payload"]
    assert compare_payload["max_position_pct"] == 0.04
    assert compare_payload["market_context"] == {
        "position_size_multiplier": 1.0,
        "risk_budget_multiplier": 0.6,
        "exposure_cap": 0.4,
        "effective_size_multiplier": 0.4,
        "allowed_strategies": ["trend_following", "breakout"],
        "blocked_strategies": ["mean_reversion"],
        "decision_notes": ["reduced exposure"],
    }
    assert [candidate["strategy"] for candidate in compare_payload["candidates"]] == ["trend_following", "breakout"]


def test_build_regime_backtest_plan_returns_no_trade_for_cash_recommendation():
    recommendation = {
        "symbol": "SPY",
        "regime": "volatile",
        "recommended_strategy": "no_trade",
        "position_size_multiplier": 0.0,
        "reason": "volatile regime favors capital protection",
    }

    plan = build_regime_backtest_plan(recommendation, {"symbols": ["AAPL"]})

    assert plan["action"] == "no_trade"
    assert plan["backtest_compare_payload"] is None
    assert plan["recommendation"] == recommendation


def test_build_regime_backtest_plan_returns_no_trade_when_allowed_empty():
    recommendation = {
        "symbol": "SPY",
        "regime": "volatile",
        "recommended_strategy": "trend_following",
        "position_size_multiplier": 1.0,
        "allowed_strategies": [],
    }

    plan = build_regime_backtest_plan(recommendation, {"symbols": ["AAPL"], "max_position_pct": 0.10})

    assert plan["action"] == "no_trade"
    assert plan["backtest_compare_payload"] is None

from app.regime_backtest_planner import build_compare_candidates, build_regime_backtest_plan


def _trade_contract(**overrides):
    recommendation = {
        "symbol": "SPY",
        "regime": "bull",
        "recommended_action": "trade",
        "recommended_strategy": "trend_following",
        "position_size_multiplier": 1.0,
        "risk_multiplier": 1.0,
        "risk_budget_multiplier": 1.0,
        "exposure_cap": 1.0,
        "allowed_strategies": ["trend_following", "breakout", "sma_crossover"],
        "data_quality": {"status": "good", "trade_allowed": True},
    }
    recommendation.update(overrides)
    return recommendation


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


def test_build_regime_backtest_plan_creates_compare_payload():
    recommendation = _trade_contract(
        position_size_multiplier=0.5,
        risk_budget_multiplier=0.5,
        exposure_cap=0.5,
        reason="bull regime favors trend-following setups",
    )
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
    assert compare_payload["market_context"]["market_regime_gate"]["decision"] == "PASS"
    assert compare_payload["candidates"][0]["strategy"] == "trend_following"
    assert {candidate["strategy"] for candidate in compare_payload["candidates"]} == {
        "sma_crossover",
        "trend_following",
        "mean_reversion",
        "breakout",
    }
    assert "strategy" not in compare_payload
    assert "fast_window" not in compare_payload
    assert "slow_window" not in compare_payload


def test_build_regime_backtest_plan_applies_market_context_limits():
    recommendation = _trade_contract(
        position_size_multiplier=1.0,
        risk_budget_multiplier=0.6,
        exposure_cap=0.4,
        allowed_strategies=["trend_following", "breakout"],
        blocked_strategies=["mean_reversion"],
        decision_notes=["reduced exposure"],
    )
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
    market_context = compare_payload["market_context"]
    assert market_context["position_size_multiplier"] == 1.0
    assert market_context["risk_budget_multiplier"] == 0.6
    assert market_context["exposure_cap"] == 0.4
    assert market_context["effective_size_multiplier"] == 0.4
    assert market_context["allowed_strategies"] == ["trend_following", "breakout"]
    assert market_context["blocked_strategies"] == ["mean_reversion"]
    assert market_context["decision_notes"] == ["reduced exposure"]
    assert market_context["market_regime_gate"]["new_entries_allowed"] is True
    assert [candidate["strategy"] for candidate in compare_payload["candidates"]] == [
        "trend_following",
        "sma_crossover",
        "mean_reversion",
        "breakout",
    ]


def test_build_regime_backtest_plan_returns_no_trade_for_market_action():
    recommendation = _trade_contract(
        regime="volatile",
        recommended_action="no_trade",
        recommended_strategy="no_trade",
        position_size_multiplier=0.0,
        risk_multiplier=0.0,
        risk_budget_multiplier=0.0,
        exposure_cap=0.0,
        allowed_strategies=[],
        reason="volatile regime favors capital protection",
    )

    plan = build_regime_backtest_plan(recommendation, {"symbols": ["AAPL"]})

    assert plan["action"] == "no_trade"
    assert plan["backtest_compare_payload"] is None
    assert plan["recommendation"] == recommendation
    assert plan["market_context"]["market_regime_gate"]["decision"] == "NO_TRADE"


def test_build_regime_backtest_plan_returns_no_trade_when_allowed_empty():
    recommendation = _trade_contract(allowed_strategies=[])

    plan = build_regime_backtest_plan(
        recommendation,
        {"symbols": ["AAPL"], "max_position_pct": 0.10},
    )

    assert plan["action"] == "no_trade"
    assert plan["backtest_compare_payload"] is None
    assert "market_regime_allowed_strategies_empty" in plan["market_context"]["market_regime_gate"]["reasons"]


def test_build_regime_backtest_plan_fails_closed_for_legacy_market_contract():
    recommendation = {
        "symbol": "SPY",
        "regime": "bull",
        "recommended_strategy": "trend_following",
        "position_size_multiplier": 1.0,
    }

    plan = build_regime_backtest_plan(recommendation, {"symbols": ["AAPL"]})

    assert plan["action"] == "no_trade"
    assert plan["backtest_compare_payload"] is None
    assert plan["market_context"]["market_regime_gate"]["decision"] == "REVIEW"

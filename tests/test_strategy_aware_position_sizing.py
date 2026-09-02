from app.regime_backtest_planner import build_regime_backtest_plan


def _recommendation(**overrides):
    payload = {
        "symbol": "SPY",
        "regime": "bull",
        "recommended_action": "trade",
        "recommended_strategy": "trend_following",
        "position_size_multiplier": 1.0,
        "risk_multiplier": 1.0,
        "risk_budget_multiplier": 1.0,
        "exposure_cap": 1.0,
        "allowed_strategies": ["trend_following"],
        "blocked_strategies": [],
        "data_quality": {"status": "good", "trade_allowed": True},
    }
    payload.update(overrides)
    return payload


def _strategy_aware(score: float):
    return {
        "status": "qualified",
        "opportunity_score": score,
        "preferred_strategy_hint": "trend_following",
        "strategy_affinity": {
            "trend_following": 0.85,
            "breakout": 0.30,
            "mean_reversion": 0.20,
        },
        "qualification_policy": {
            "mode": "strategy_aware",
            "generic_score": score,
            "strategy_name": "trend_following",
            "strategy_affinity": 0.85,
            "hard_execution_safe": True,
            "hard_execution_thresholds_relaxed": False,
        },
    }


def _generic():
    return {
        "status": "qualified",
        "opportunity_score": 0.82,
        "preferred_strategy_hint": "trend_following",
        "strategy_affinity": {"trend_following": 0.85},
        "qualification_policy": {"mode": "generic", "generic_score": 0.82},
    }


def test_strategy_aware_candidate_below_060_is_capped_at_quarter_size():
    plan = build_regime_backtest_plan(
        _recommendation(),
        {"symbols": ["ABC"], "max_position_pct": 0.10},
        opportunity_profile=_strategy_aware(0.58),
    )

    assert plan["action"] == "compare"
    context = plan["market_context"]
    assert context["scanner_opportunity_size_multiplier"] == 0.25
    assert context["effective_size_multiplier"] == 0.25
    assert plan["backtest_compare_payload"]["max_position_pct"] == 0.025


def test_strategy_aware_candidate_from_060_to_070_is_capped_at_half_size():
    plan = build_regime_backtest_plan(
        _recommendation(),
        {"symbols": ["ABC"], "max_position_pct": 0.10},
        opportunity_profile=_strategy_aware(0.65),
    )

    assert plan["action"] == "compare"
    context = plan["market_context"]
    assert context["scanner_opportunity_size_multiplier"] == 0.50
    assert context["effective_size_multiplier"] == 0.50
    assert plan["backtest_compare_payload"]["max_position_pct"] == 0.05


def test_generic_qualified_candidate_keeps_existing_size_policy():
    plan = build_regime_backtest_plan(
        _recommendation(),
        {"symbols": ["ABC"], "max_position_pct": 0.10},
        opportunity_profile=_generic(),
    )

    assert plan["action"] == "compare"
    context = plan["market_context"]
    assert context["scanner_opportunity_size_multiplier"] == 1.0
    assert context["effective_size_multiplier"] == 1.0
    assert plan["backtest_compare_payload"]["max_position_pct"] == 0.10


def test_market_regime_cap_remains_stricter_than_strategy_aware_cap():
    plan = build_regime_backtest_plan(
        _recommendation(exposure_cap=0.40),
        {"symbols": ["ABC"], "max_position_pct": 0.10},
        opportunity_profile=_strategy_aware(0.65),
    )

    assert plan["action"] == "compare"
    context = plan["market_context"]
    assert context["scanner_opportunity_size_multiplier"] == 0.50
    assert context["exposure_cap"] == 0.40
    assert context["effective_size_multiplier"] == 0.40
    assert plan["backtest_compare_payload"]["max_position_pct"] == 0.04

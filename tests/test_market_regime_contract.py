from app.market_regime_contract import (
    evaluate_market_regime_gate,
    market_regime_envelope_issues,
)


def _trade_recommendation(*, quality_status="good", trade_allowed=True):
    return {
        "symbol": "SPY",
        "regime": "bull",
        "risk_level": "low",
        "recommended_action": "trade",
        "recommended_strategy": "trend_following",
        "position_size_multiplier": 1.0,
        "risk_multiplier": 1.0,
        "risk_budget_multiplier": 1.0,
        "exposure_cap": 1.0,
        "allowed_strategies": ["trend_following", "breakout"],
        "data_quality": {
            "status": quality_status,
            "trade_allowed": trade_allowed,
        },
    }


def test_market_regime_gate_allows_explicit_trade_with_good_quality():
    gate = evaluate_market_regime_gate({}, _trade_recommendation())

    assert gate["new_entries_allowed"] is True
    assert gate["decision"] == "PASS"
    assert gate["reasons"] == []


def test_market_regime_gate_allows_review_quality_only_when_trade_allowed():
    gate = evaluate_market_regime_gate(
        {},
        _trade_recommendation(quality_status="review", trade_allowed=True),
    )

    assert gate["new_entries_allowed"] is True
    assert gate["warnings"] == ["market_regime_data_quality_review"]


def test_market_regime_gate_blocks_legacy_contract_without_quality_or_action():
    gate = evaluate_market_regime_gate(
        {},
        {
            "recommended_strategy": "trend_following",
            "position_size_multiplier": 1.0,
            "risk_multiplier": 1.0,
            "risk_budget_multiplier": 1.0,
            "exposure_cap": 1.0,
            "allowed_strategies": ["trend_following"],
        },
    )

    assert gate["new_entries_allowed"] is False
    assert gate["decision"] == "REVIEW"
    assert "market_regime_data_quality_missing" in gate["reasons"]
    assert "market_regime_recommended_action_missing_or_invalid" in gate["reasons"]


def test_market_regime_gate_blocks_no_trade_action_without_crashing_review_flow():
    recommendation = _trade_recommendation()
    recommendation.update(
        recommended_action="no_trade",
        recommended_strategy="no_trade",
        allowed_strategies=[],
        position_size_multiplier=0.0,
        risk_multiplier=0.0,
        risk_budget_multiplier=0.0,
        exposure_cap=0.0,
    )

    gate = evaluate_market_regime_gate({}, recommendation)

    assert gate["new_entries_allowed"] is False
    assert gate["decision"] == "NO_TRADE"
    assert gate["reasons"] == ["market_regime_recommended_no_trade"]


def test_market_regime_gate_blocks_data_quality_even_when_action_says_trade():
    gate = evaluate_market_regime_gate(
        {},
        _trade_recommendation(quality_status="blocked", trade_allowed=False),
    )

    assert gate["new_entries_allowed"] is False
    assert "market_regime_data_quality_blocks_trade" in gate["reasons"]
    assert "market_regime_data_quality_blocked" in gate["reasons"]


def test_market_regime_envelope_requires_v11_and_matching_correlation_id():
    issues = market_regime_envelope_issues(
        {
            "status": "success",
            "agent_type": "market-regime-agent",
            "schema_version": "1.0",
            "correlation_id": "different",
            "data": {},
        },
        "expected",
    )

    assert "market_regime_schema_version_mismatch" in issues
    assert "market_regime_correlation_id_mismatch" in issues

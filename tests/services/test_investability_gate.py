import pytest

from app.services.investability_gate import (
    evaluate_investability,
    filter_candidates_with_investability_gate,
)


def _candidate(
    symbol="AAPL",
    *,
    price=190.0,
    market_cap=3_000_000_000_000.0,
    atr_percent=2.5,
    volatility_regime="normal",
    average_volume=None,
    bid=None,
    ask=None,
):
    technical = {
        "current_price": price,
        "atr_percent": atr_percent,
        "volatility_regime": volatility_regime,
    }
    if average_volume is not None:
        technical["average_daily_volume"] = average_volume
    if bid is not None:
        technical["bid"] = bid
    if ask is not None:
        technical["ask"] = ask
    return {
        "symbol": symbol,
        "strategy_bucket": "value_rebound",
        "evidence_summary": {
            "raw_scores": {
                "scanner": {"market_cap": market_cap},
                "technical": technical,
            }
        },
    }


def _evaluate(candidate, **overrides):
    settings = {
        "enabled": True,
        "min_price_usd": 3.0,
        "min_market_cap_usd": 300_000_000.0,
        "min_average_dollar_volume_usd": 5_000_000.0,
        "max_spread_bps": 100.0,
        "max_atr_pct": 15.0,
        "require_average_dollar_volume": False,
        "require_spread": False,
        "require_atr": True,
        "block_extreme_volatility": True,
    }
    settings.update(overrides)
    return evaluate_investability(candidate, **settings)


def test_large_liquid_security_passes_with_optional_liquidity_warnings():
    decision = _evaluate(_candidate())

    assert decision["allowed"] is True
    assert decision["status"] == "pass"
    assert "investability_average_dollar_volume_missing" in decision[
        "warning_codes"
    ]
    assert "investability_spread_missing" in decision["warning_codes"]


def test_mbai_like_microcap_is_blocked_before_backtest():
    decision = _evaluate(
        _candidate(
            "MBAI",
            price=1.01,
            market_cap=7_846_314.0,
            atr_percent=11.3457,
            volatility_regime="extreme",
        )
    )

    assert decision["allowed"] is False
    assert decision["status"] == "block"
    assert set(decision["rejection_codes"]) >= {
        "investability_price_below_minimum",
        "investability_market_cap_below_minimum",
        "investability_extreme_volatility",
    }


def test_missing_required_atr_is_quarantined_not_imputed():
    decision = _evaluate(_candidate(atr_percent=None))

    assert decision["allowed"] is False
    assert decision["status"] == "quarantine"
    assert decision["metrics"]["atr_percent"] is None
    assert decision["rejection_codes"] == ["investability_atr_missing"]


def test_average_dollar_volume_and_spread_are_derived_when_available():
    decision = _evaluate(
        _candidate(
            price=10.0,
            average_volume=100_000.0,
            bid=9.90,
            ask=10.10,
        ),
        require_average_dollar_volume=True,
        require_spread=True,
    )

    assert decision["metrics"]["average_dollar_volume"] == pytest.approx(
        1_000_000.0
    )
    assert decision["metrics"]["spread_bps"] == pytest.approx(200.0)
    assert set(decision["rejection_codes"]) == {
        "investability_average_dollar_volume_below_minimum",
        "investability_spread_above_maximum",
    }


def test_filter_preserves_only_passed_positions_and_payloads():
    good = _candidate("AAPL")
    bad = _candidate(
        "MBAI",
        price=1.01,
        market_cap=7_846_314.0,
        volatility_regime="extreme",
    )
    result = filter_candidates_with_investability_gate(
        selected_positions=[good, bad],
        position_analysis_payloads=[
            {"ticker": "AAPL", **good},
            {"ticker": "MBAI", **bad},
        ],
        enabled=True,
        min_price_usd=3.0,
        min_market_cap_usd=300_000_000.0,
        min_average_dollar_volume_usd=5_000_000.0,
        max_spread_bps=100.0,
        max_atr_pct=15.0,
        require_average_dollar_volume=False,
        require_spread=False,
        require_atr=True,
        block_extreme_volatility=True,
    )

    assert [row["symbol"] for row in result["selected_positions"]] == [
        "AAPL"
    ]
    assert [row["ticker"] for row in result["position_analysis_payloads"]] == [
        "AAPL"
    ]
    assert result["summary"]["allowed_count"] == 1
    assert result["summary"]["blocked_count"] == 1

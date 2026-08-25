from app.services.research_strategy_compatibility_service import (
    COMPATIBILITY_GATE_SCHEMA,
    preflight_research_strategy_compatibility,
)


BACKTEST_CONTRACT = {
    "schema_version": "strategy-bucket-compatibility.v1",
    "profile": "balanced_v1",
    "bucket_strategy_families": {
        "core_dividend": ["trend_following", "sma_crossover"],
        "value_rebound": ["mean_reversion", "sma_crossover"],
        "news_momentum": ["breakout", "trend_following"],
    },
    "backtest_remains_authoritative": True,
    "thresholds_relaxed": False,
}


def _market_context(allowed):
    return {
        "market_strategy": {
            "regime": "bull",
            "risk_level": "low",
            "recommended_action": "trade",
            "allowed_strategies": allowed,
        },
        "market_regime_gate": {
            "gate_version": "manager-market-regime-gate.v1",
            "decision": "PASS",
            "new_entries_allowed": True,
            "recommended_action": "trade",
        },
    }


def _row(symbol, bucket):
    return {
        "symbol": symbol,
        "strategy_bucket": bucket,
        "bucket_classification_status": "classified",
        "bucket_confidence": 0.9,
        "evidence_gate_passed": True,
    }


def test_bull_regime_rejects_value_rebound_when_only_sma_intersects():
    rows = [
        _row("VALUE", "value_rebound"),
        _row("NEWS", "news_momentum"),
        _row("CORE", "core_dividend"),
    ]

    retained, gate = preflight_research_strategy_compatibility(
        rows,
        backtest_contract=BACKTEST_CONTRACT,
        market_context=_market_context(
            ["trend_following", "breakout", "sma_crossover"]
        ),
        min_compatible_strategies=2,
    )

    assert [row["symbol"] for row in retained] == ["NEWS", "CORE"]
    assert gate["schema_version"] == COMPATIBILITY_GATE_SCHEMA
    assert gate["status"] == "completed_with_backfill"
    assert gate["rejected_symbols"] == ["VALUE"]
    value = next(row for row in gate["evaluations"] if row["symbol"] == "VALUE")
    assert value["compatible_strategy_families"] == ["sma_crossover"]
    assert value["compatible_strategy_count"] == 1
    assert value["decision"] == "exclude_and_backfill"


def test_unknown_backtest_contract_defers_instead_of_guessing():
    rows = [_row("VALUE", "value_rebound")]

    retained, gate = preflight_research_strategy_compatibility(
        rows,
        backtest_contract={},
        market_context=_market_context(["sma_crossover"]),
        min_compatible_strategies=2,
    )

    assert [row["symbol"] for row in retained] == ["VALUE"]
    assert gate["status"] == "deferred_contract_unavailable"
    assert gate["rejected_symbols"] == []
    assert gate["unknown_symbols"] == ["VALUE"]
    assert gate["safety"]["unknown_evidence_deferred_to_exact_backtest"] is True


def test_non_tradeable_regime_does_not_invent_an_intersection_gate():
    context = _market_context([])
    context["market_strategy"]["recommended_action"] = "no_trade"
    context["market_regime_gate"].update(
        {
            "decision": "BLOCK",
            "new_entries_allowed": False,
            "recommended_action": "no_trade",
        }
    )

    retained, gate = preflight_research_strategy_compatibility(
        [_row("VALUE", "value_rebound")],
        backtest_contract=BACKTEST_CONTRACT,
        market_context=context,
        min_compatible_strategies=2,
    )

    assert [row["symbol"] for row in retained] == ["VALUE"]
    assert gate["status"] == "not_applicable_market_policy"
    assert gate["rejected_symbols"] == []


def test_compatibility_gate_never_grants_trade_authority_or_relaxes_backtest():
    retained, gate = preflight_research_strategy_compatibility(
        [_row("NEWS", "news_momentum")],
        backtest_contract=BACKTEST_CONTRACT,
        market_context=_market_context(["trend_following", "breakout"]),
        min_compatible_strategies=2,
    )

    assert retained
    evidence = retained[0]["pre_backtest_strategy_compatibility"]
    assert evidence["production_authority_granted"] is False
    assert evidence["risk_execution_authority_granted"] is False
    assert evidence["backtest_thresholds_relaxed"] is False
    assert gate["safety"]["backtest_remains_authoritative"] is True

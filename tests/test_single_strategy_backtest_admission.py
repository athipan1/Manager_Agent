from app.services import research_strategy_compatibility_service as compatibility


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


def _market(allowed):
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


def _row(symbol="TCOM", bucket="value_rebound"):
    return {
        "symbol": symbol,
        "strategy_bucket": bucket,
        "bucket_classification_status": "classified",
        "bucket_confidence": 0.80,
        "evidence_gate_passed": True,
    }


def test_default_admission_requires_one_compatible_strategy_not_two():
    assert compatibility.DEFAULT_MIN_COMPATIBLE_STRATEGIES == 1

    retained, gate = compatibility.preflight_research_strategy_compatibility(
        [_row()],
        backtest_contract=BACKTEST_CONTRACT,
        market_context=_market(["trend_following", "breakout", "sma_crossover"]),
    )

    assert [row["symbol"] for row in retained] == ["TCOM"]
    evidence = gate["evaluations"][0]
    assert evidence["compatible_strategy_families"] == ["sma_crossover"]
    assert evidence["compatible_strategy_count"] == 1
    assert evidence["minimum_compatible_strategies"] == 1
    assert evidence["decision"] == "eligible_for_exact_backtest"
    assert evidence["admission_only"] is True
    assert evidence["exact_backtest_required"] is True
    assert evidence["production_authority_granted"] is False
    assert evidence["risk_execution_authority_granted"] is False
    assert evidence["backtest_thresholds_relaxed"] is False
    assert gate["admission_policy"]["production_binding"] is False
    assert gate["safety"]["backtest_remains_authoritative"] is True


def test_empty_strategy_intersection_remains_fail_closed():
    retained, gate = compatibility.preflight_research_strategy_compatibility(
        [_row()],
        backtest_contract=BACKTEST_CONTRACT,
        market_context=_market(["breakout", "trend_following"]),
    )

    assert retained == []
    assert gate["rejected_symbols"] == ["TCOM"]
    evidence = gate["evaluations"][0]
    assert evidence["compatible_strategy_count"] == 0
    assert evidence["decision"] == "exclude_and_backfill"


def test_operator_can_keep_stricter_two_strategy_admission_override():
    retained, gate = compatibility.preflight_research_strategy_compatibility(
        [_row()],
        backtest_contract=BACKTEST_CONTRACT,
        market_context=_market(["trend_following", "breakout", "sma_crossover"]),
        min_compatible_strategies=2,
    )

    assert retained == []
    assert gate["minimum_compatible_strategies"] == 2
    assert gate["rejected_symbols"] == ["TCOM"]


def test_runtime_minimum_defaults_to_one_and_accepts_stricter_override(monkeypatch):
    monkeypatch.delenv("BACKTEST_RESEARCH_MIN_COMPATIBLE_STRATEGIES", raising=False)
    assert compatibility._runtime_minimum() == 1

    monkeypatch.setenv("BACKTEST_RESEARCH_MIN_COMPATIBLE_STRATEGIES", "2")
    assert compatibility._runtime_minimum() == 2

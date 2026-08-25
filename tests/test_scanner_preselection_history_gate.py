from __future__ import annotations

import pytest

from scripts.run_scanner_preselection import (
    _history_gate_research_selection,
    _required_backtest_history_bars,
)


def _ranked(symbol: str, score: float) -> dict:
    return {
        "symbol": symbol,
        "strategy_bucket": "value_rebound",
        "bucket_confidence": 0.90,
        "bucket_classification_status": "classified",
        "evidence_gate_passed": True,
        "final_verdict": "hold",
        "score_breakdown": {"final_opportunity_score": score},
        "scanner_candidate": {
            "metadata": {
                "details": {
                    "data_bundle": {
                        "opportunity_profile": {"fail_closed": False}
                    }
                }
            }
        },
    }


def _data() -> dict:
    return {
        "bucket_selection": {"summary": {"min_final_score": 0.55}},
        "ranked_candidates": [
            _ranked("YB", 0.72),
            _ranked("ZJK", 0.70),
            _ranked("NAGE", 0.68),
        ],
    }


def test_default_nested_history_contract_requires_882_bars(monkeypatch):
    for name in (
        "BACKTEST_HISTORY_REQUIRED_BARS",
        "BACKTEST_NESTED_MINIMUM_BARS",
        "BACKTEST_FINAL_HOLDOUT_BARS",
        "BACKTEST_FINAL_HOLDOUT_ENABLED",
    ):
        monkeypatch.delenv(name, raising=False)

    assert _required_backtest_history_bars() == 882


def test_known_insufficient_history_is_excluded_and_next_candidate_backfills(monkeypatch):
    monkeypatch.delenv("BACKTEST_HISTORY_REQUIRED_BARS", raising=False)
    observed = {"YB": 330, "ZJK": 900, "NAGE": 950}

    selection, gate = _history_gate_research_selection(
        _data(),
        fetch_bar_count=lambda symbol, required: observed[symbol],
    )

    assert [row["symbol"] for row in selection["selected"]] == ["ZJK", "NAGE"]
    assert gate["required_bars"] == 882
    assert gate["rejected_symbols"] == ["YB"]
    assert gate["backfilled_selection_count"] == 2
    yb = next(row for row in gate["evaluations"] if row["symbol"] == "YB")
    assert yb == {
        "symbol": "YB",
        "status": "insufficient_history",
        "bars_observed": 330,
        "bars_required": 882,
        "history_eligible": False,
        "decision": "exclude_and_backfill",
    }
    assert gate["safety"]["production_authority_granted"] is False
    assert gate["safety"]["risk_execution_authority_granted"] is False
    assert gate["safety"]["backtest_thresholds_relaxed"] is False


def test_unknown_history_is_deferred_to_exact_backtest_not_falsely_rejected(monkeypatch):
    monkeypatch.delenv("BACKTEST_HISTORY_REQUIRED_BARS", raising=False)

    selection, gate = _history_gate_research_selection(
        _data(),
        fetch_bar_count=lambda symbol, required: None,
    )

    assert [row["symbol"] for row in selection["selected"]] == ["YB", "ZJK"]
    assert gate["rejected_symbols"] == []
    assert gate["unknown_symbols"] == ["YB", "ZJK", "NAGE"]
    assert all(
        row["decision"] == "defer_to_exact_backtest"
        for row in gate["evaluations"]
    )
    assert gate["safety"]["unknown_history_deferred_to_exact_backtest"] is True


def test_explicit_required_history_override_is_supported(monkeypatch):
    monkeypatch.setenv("BACKTEST_HISTORY_REQUIRED_BARS", "1000")
    assert _required_backtest_history_bars() == 1000


@pytest.mark.parametrize("value", ["0", "-1", "not-an-int"])
def test_invalid_required_history_override_fails_closed(monkeypatch, value):
    monkeypatch.setenv("BACKTEST_HISTORY_REQUIRED_BARS", value)
    with pytest.raises(ValueError):
        _required_backtest_history_bars()


def test_disabled_final_holdout_fails_closed_for_nested_promotion(monkeypatch):
    monkeypatch.delenv("BACKTEST_HISTORY_REQUIRED_BARS", raising=False)
    monkeypatch.setenv("BACKTEST_FINAL_HOLDOUT_ENABLED", "false")

    with pytest.raises(ValueError, match="FINAL_HOLDOUT_ENABLED"):
        _required_backtest_history_bars()

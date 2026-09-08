from enum import Enum

import pytest

from app.synthesis import get_weighted_verdict_trace
from app.workflows.analysis_workflow import (
    analyze_single_asset,
    clear_deep_analysis_cache,
    process_agent_response,
)
from app.services.serialization_service import normalize_score
from scripts.build_decision_trace import build_report


def envelope(action, confidence):
    return {
        "status": "success",
        "data": {"action": action, "confidence_score": confidence, "reason": "observed inputs"},
    }


def test_hold_score_is_not_a_buy_and_single_supported_vote_can_buy():
    hold = get_weighted_verdict_trace("hold", 0.99, "hold", 0.99, "TEST")
    buy = get_weighted_verdict_trace("buy", 0.75, "hold", 0.55, "TEST")
    assert hold["verdict"] == "hold" and hold["directional_score"] == 0
    assert buy["verdict"] == "buy" and buy["directional_score"] == 0.375
    assert buy["thresholds"]["buy"] == 0.2


def test_enum_case_and_invalid_contract_diagnostics():
    class Action(str, Enum):
        BUY = "buy"

    assert process_agent_response(envelope(Action.BUY, 0.75), "technical").action == "buy"
    assert process_agent_response(envelope(" BUY ", 0.75), "technical").action == "buy"
    invalid = process_agent_response(envelope("moon", 0.99), "technical")
    assert invalid.action == "hold" and invalid.score == 0
    assert "Invalid" in invalid.reason
    assert normalize_score(float("nan")) == 0
    assert normalize_score(float("inf")) == 0


@pytest.mark.asyncio
async def test_changed_scanner_evidence_cannot_reuse_cached_hold(monkeypatch):
    clear_deep_analysis_cache()
    context = {"revision": 1}
    calls = []
    monkeypatch.setattr("app.workflows.analysis_workflow.get_scanner_prefetch", lambda ticker: dict(context))

    async def agents(ticker, correlation):
        calls.append(correlation)
        return envelope("hold" if context["revision"] == 1 else "buy", 0.75), envelope("hold", 0.55)

    monkeypatch.setattr("app.workflows.analysis_workflow.call_agents", agents)
    first = await analyze_single_asset("AAPL", "cycle-1")
    context["revision"] = 2
    second = await analyze_single_asset("AAPL", "cycle-2")
    assert first["final_verdict"] == "hold"
    assert second["final_verdict"] == "buy"
    assert len(calls) == 2 and second["analysis_cache"]["hit"] is False
    assert second["decision_trace"]["aggregation"]["directional_score"] == 0.375
    clear_deep_analysis_cache()


def test_stage_report_does_not_infer_risk_or_execution_from_score():
    source = {
        "request": {"min_final_score": 0.55},
        "response": {
            "status": "success",
            "data": {
                "report_id": "cycle",
                "scanner_count": 1,
                "top_10_symbols": ["AAPL"],
                "ranked_candidates": [
                    {
                        "symbol": "AAPL",
                        "final_verdict": "hold",
                        "score_breakdown": {"final_opportunity_score": 0.9},
                    }
                ],
                "pre_gate_selected_positions": [],
                "pre_backtest_selected_positions": [],
                "exposure_gate": {"summary": {"allowed_count": 0}},
            },
        },
    }
    report = build_report(source, {}, {"reason": "market_closed"}, {})
    row = report["symbols"][0]
    assert row["scanner_pass"] is True and row["score_pass"] is True
    assert row["verdict_pass"] is False and row["allocation_pass"] is False
    assert row["backtest_pass"] is None and row["risk_pass"] is None
    assert row["execution_authorized"] is False


def test_missing_backtest_identity_never_counts_as_same_cycle():
    report = build_report({}, {"data": {"eligible_symbols": ["AAPL"], "items": [{"symbol": "AAPL"}]}}, {}, {})
    assert report["symbols"][0]["backtest_pass"] is None

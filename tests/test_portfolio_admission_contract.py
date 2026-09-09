"""Contract fixtures test gates; they are never submitted to a broker."""
from decimal import Decimal

import pytest

from app.discover_allocation import (
    build_discover_allocation_plan, enrich_ranked_candidates_with_buckets,
    select_candidates_by_bucket,
)
from app.discover_report_builder import build_position_analysis_payloads, build_selected_positions
from app.risk_manager import _normalize_stock_context


def candidate(symbol, bucket, score, verdict="buy"):
    return {"symbol": symbol, "analysis": {"ticker": symbol, "final_verdict": verdict,
            "status": "complete", "details": {}},
            "scanner_candidate": {"metadata": {"primary_strategy_bucket_hint": bucket,
                "strategy_bucket_hints": [bucket], "bucket_hint_scores": {bucket: .9}}},
            "score_breakdown": {"final_opportunity_score": score}}


@pytest.mark.parametrize("bucket,score,minimum", [
    ("value_rebound", .57, .58), ("news_momentum", .61, .62)])
def test_bucket_minimum_is_enforced_by_selection(bucket, score, minimum):
    selection = select_candidates_by_bucket([candidate("TEST", bucket, score)], min_final_score=.55)
    assert selection[bucket]["selected_count"] == 0
    decision = selection["selection_evaluations"][0]
    assert decision["final_score_passed"] is True
    rejection = next(r for r in decision["rejections"] if r["reason_code"] == "BUCKET_SCORE_BELOW_THRESHOLD")
    assert rejection["observed"] == score and rejection["threshold"] == minimum


def test_global_minimum_and_buy_verdict_remain_required():
    rows = [candidate("LOW", "value_rebound", .60), candidate("HOLD", "value_rebound", .95, "hold")]
    selection = select_candidates_by_bucket(rows, min_final_score=.65)
    assert selection["summary"]["total_selected"] == 0
    assert any(r["reason_code"] == "BUY_VERDICT_REQUIRED" for r in selection["selection_evaluations"][1]["rejections"])


def test_symbol_allocation_weight_is_distinct_from_bucket_target():
    ranked = enrich_ranked_candidates_with_buckets([candidate("TEST", "core_dividend", .8)])
    plan = build_discover_allocation_plan(ranked, Decimal("100000"))
    selected = build_selected_positions(ranked=ranked, allocation_plan=plan,
                                       bucket_selection=select_candidates_by_bucket(ranked))
    row = selected[0]
    assert row["target_value"] == 10000
    assert row["allocation_weight"] == .10
    assert row["bucket_target_weight"] == .50
    payload = build_position_analysis_payloads(ranked=ranked, selected_positions=selected)[0]
    assert payload["portfolio_context"]["allocation_weight"] == .10


def test_explicit_unassigned_bucket_is_not_relabelled_before_risk():
    context = _normalize_stock_context({"strategy_bucket": "unassigned"}, current_position_size=0,
        symbol_exposure=Decimal(0), has_explicit_symbol_exposure=True)
    assert context["strategy_bucket"] == "unassigned"


@pytest.mark.parametrize("debt", [None, 1.5])
def test_missing_or_high_canonical_debt_does_not_establish_low_debt(monkeypatch, debt):
    from app.strategy_bucket_classifier import classify_candidate_strategy_bucket
    summary = {"gate_required": False, "classification_inputs": {
        "fundamental": {"quality_score": .66, "free_cash_flow": 100000,
                        "debt_to_equity": debt}}, "sources": {}}
    monkeypatch.setattr("app.strategy_bucket_classifier.build_analysis_evidence_summary", lambda item: summary)
    decision = classify_candidate_strategy_bucket({"score_breakdown": {"final_opportunity_score": .8}})
    assert decision.allows_new_entry is False
    assert "quality_cashflow_low_debt" not in decision.reasons
    assert decision.evidence_summary["classification_rule_trace"]["effective_inputs"]["debt_to_equity"] == debt

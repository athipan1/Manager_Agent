from decimal import Decimal

from app.discover_allocation import (
    build_discover_allocation_plan,
    choose_bucket_aware_winner,
    enrich_ranked_candidates_with_buckets,
    ranked_response_rows,
    select_candidates_by_bucket,
)
from app.discover_report_builder import build_discover_allocation_report


def _item(symbol, score, verdict="buy", tags=None, raw_scores=None):
    return {
        "symbol": symbol,
        "analysis": {"ticker": symbol, "final_verdict": verdict, "status": "complete", "details": {}},
        "scanner_candidate": {"metadata": {"tags": tags or []}, "raw_scores": raw_scores or {}},
        "score_breakdown": {"final_opportunity_score": score},
    }


def test_enrich_ranked_candidates_adds_strategy_bucket():
    ranked = [_item("KO", 0.66, tags=["dividend"]), _item("NEWS", 0.70, tags=["news"])]

    enriched = enrich_ranked_candidates_with_buckets(ranked)

    assert enriched[0]["strategy_bucket"] == "core_dividend"
    assert enriched[0]["score_breakdown"]["strategy_bucket"] == "core_dividend"
    assert enriched[1]["strategy_bucket"] == "news_momentum"


def test_build_discover_allocation_plan_contains_50_30_20_buckets():
    ranked = [
        _item("KO", 0.66, tags=["dividend"]),
        _item("ACGL", 0.61, raw_scores={"pe_ratio": 12}),
        _item("NEWS", 0.70, tags=["news"]),
    ]

    plan = build_discover_allocation_plan(ranked, Decimal("100000"))

    assert plan["policy_name"] == "core_satellite_50_30_20"
    assert plan["buckets"]["core_dividend"]["target_value"] == 50000.0
    assert plan["buckets"]["value_rebound"]["target_value"] == 30000.0
    assert plan["buckets"]["news_momentum"]["target_value"] == 20000.0


def test_choose_bucket_aware_winner_prefers_core_when_eligible():
    ranked = [
        _item("NEWS", 0.90, tags=["news"]),
        _item("KO", 0.66, tags=["dividend"]),
        _item("ACGL", 0.80, raw_scores={"pe_ratio": 12}),
    ]
    plan = build_discover_allocation_plan(ranked, Decimal("100000"))

    winner = choose_bucket_aware_winner(ranked, plan, min_final_score=0.55)

    assert winner["symbol"] == "KO"
    assert winner["strategy_bucket"] == "core_dividend"


def test_choose_bucket_aware_winner_falls_back_to_best_eligible_when_bucket_empty():
    ranked = [_item("NEWS", 0.90, tags=["news"]), _item("ACGL", 0.80, raw_scores={"pe_ratio": 12})]
    plan = build_discover_allocation_plan(ranked, Decimal("100000"))

    winner = choose_bucket_aware_winner(ranked, plan, min_final_score=0.55)

    assert winner["symbol"] == "ACGL"
    assert winner["strategy_bucket"] == "value_rebound"


def test_ranked_response_rows_include_strategy_bucket():
    ranked = [_item("NEWS", 0.70, tags=["news"])]

    rows = ranked_response_rows(ranked)

    assert rows[0]["strategy_bucket"] == "news_momentum"
    assert rows[0]["score_breakdown"]["strategy_bucket"] == "news_momentum"


def test_select_candidates_by_bucket_uses_default_limits():
    ranked = [
        _item("KO", 0.80, tags=["dividend"]),
        _item("JNJ", 0.75, tags=["dividend"]),
        _item("PEP", 0.70, tags=["dividend"]),
        _item("ACGL", 0.82, raw_scores={"pe_ratio": 12}),
        _item("ADBE", 0.78, raw_scores={"pe_ratio": 14}),
        _item("AMZN", 0.76, raw_scores={"pe_ratio": 16}),
        _item("NEWS1", 0.90, tags=["news"]),
        _item("NEWS2", 0.88, tags=["news"]),
    ]

    selection = select_candidates_by_bucket(ranked, min_final_score=0.55)

    assert selection["core_dividend"]["selected_count"] == 2
    assert [row["symbol"] for row in selection["core_dividend"]["selected"]] == ["KO", "JNJ"]
    assert selection["value_rebound"]["selected_count"] == 2
    assert [row["symbol"] for row in selection["value_rebound"]["selected"]] == ["ACGL", "ADBE"]
    assert selection["news_momentum"]["selected_count"] == 1
    assert [row["symbol"] for row in selection["news_momentum"]["selected"]] == ["NEWS1"]
    assert selection["summary"]["total_selected"] == 5


def test_build_discover_allocation_report_includes_bucket_selection():
    ranked = [
        _item("KO", 0.80, tags=["dividend"]),
        _item("ACGL", 0.82, raw_scores={"pe_ratio": 12}),
        _item("NEWS1", 0.90, tags=["news"]),
    ]

    report = build_discover_allocation_report(ranked=ranked, portfolio_value=Decimal("100000"), min_final_score=0.55)

    assert "bucket_selection" in report
    assert report["bucket_selection"]["summary"]["total_selected"] == 3
    assert report["bucket_selection"]["core_dividend"]["selected"][0]["symbol"] == "KO"
    assert report["bucket_selection"]["value_rebound"]["selected"][0]["symbol"] == "ACGL"
    assert report["bucket_selection"]["news_momentum"]["selected"][0]["symbol"] == "NEWS1"

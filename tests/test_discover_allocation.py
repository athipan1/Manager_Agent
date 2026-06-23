from decimal import Decimal

from app.discover_allocation import (
    build_discover_allocation_plan,
    choose_bucket_aware_winner,
    enrich_ranked_candidates_with_buckets,
    ranked_response_rows,
)


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

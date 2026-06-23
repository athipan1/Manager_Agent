from decimal import Decimal

from app.portfolio_allocation import (
    CORE_DIVIDEND,
    NEWS_MOMENTUM,
    VALUE_REBOUND,
    build_strategy_allocation_plan,
    classify_strategy_bucket,
)


def _candidate(symbol, score=0.7, tags=None, raw_scores=None, metadata=None):
    return {
        "symbol": symbol,
        "analysis": {"ticker": symbol, "final_verdict": "buy", "details": {}},
        "scanner_candidate": {
            "metadata": metadata or {},
            "raw_scores": raw_scores or {},
        },
        "score_breakdown": {"final_opportunity_score": score},
        "tags": tags or [],
    }


def test_default_allocation_policy_is_50_30_20():
    plan = build_strategy_allocation_plan([], Decimal("100000"))

    assert plan["policy_name"] == "core_satellite_50_30_20"
    assert plan["is_weight_balanced"] is True
    assert plan["buckets"][CORE_DIVIDEND]["target_weight"] == 0.5
    assert plan["buckets"][VALUE_REBOUND]["target_weight"] == 0.3
    assert plan["buckets"][NEWS_MOMENTUM]["target_weight"] == 0.2
    assert plan["buckets"][CORE_DIVIDEND]["target_value"] == 50000.0
    assert plan["buckets"][VALUE_REBOUND]["target_value"] == 30000.0
    assert plan["buckets"][NEWS_MOMENTUM]["target_value"] == 20000.0


def test_classify_core_dividend_from_dividend_or_defensive_sector():
    dividend = _candidate("KO", raw_scores={"dividend_yield": 0.03})
    defensive = _candidate("JNJ", metadata={"sector": "Healthcare"})

    assert classify_strategy_bucket(dividend) == CORE_DIVIDEND
    assert classify_strategy_bucket(defensive) == CORE_DIVIDEND


def test_classify_value_rebound_from_low_valuation():
    value = _candidate("VALUE", raw_scores={"pe_ratio": 12, "pb_ratio": 1.2})

    assert classify_strategy_bucket(value) == VALUE_REBOUND


def test_classify_news_momentum_from_tags():
    news = _candidate("NEWS", tags=["news", "catalyst", "volume"])

    assert classify_strategy_bucket(news) == NEWS_MOMENTUM


def test_allocation_plan_assigns_candidates_to_buckets():
    ranked = [
        _candidate("KO", score=0.66, raw_scores={"dividend_yield": 0.03}),
        _candidate("VALUE", score=0.61, raw_scores={"pe_ratio": 12}),
        _candidate("NEWS", score=0.70, tags=["news", "catalyst"]),
    ]

    plan = build_strategy_allocation_plan(ranked, Decimal("100000"))

    assert [c["symbol"] for c in plan["buckets"][CORE_DIVIDEND]["candidates"]] == ["KO"]
    assert [c["symbol"] for c in plan["buckets"][VALUE_REBOUND]["candidates"]] == ["VALUE"]
    assert [c["symbol"] for c in plan["buckets"][NEWS_MOMENTUM]["candidates"]] == ["NEWS"]
    assert plan["buckets"][CORE_DIVIDEND]["candidates"][0]["suggested_max_value"] == 10000.0
    assert plan["buckets"][VALUE_REBOUND]["candidates"][0]["suggested_max_value"] == 7000.0
    assert plan["buckets"][NEWS_MOMENTUM]["candidates"][0]["suggested_max_value"] == 3000.0

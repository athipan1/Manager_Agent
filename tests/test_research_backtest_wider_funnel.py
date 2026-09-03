from app.services.research_backtest_selection_service import (
    AUTO_CLASSIFY_THRESHOLD,
    DEFAULT_RESEARCH_BUCKET_LIMITS,
    EXPLORATORY_BUCKET,
    select_research_backtest_candidates,
)


def _row(
    symbol: str,
    *,
    bucket: str = "value_rebound",
    status: str = "classified",
    confidence: float = 0.80,
    score: float = 0.65,
    verdict: str = "buy",
):
    return {
        "symbol": symbol,
        "strategy_bucket": bucket,
        "bucket_classification_status": status,
        "bucket_confidence": confidence,
        "evidence_gate_passed": True,
        "final_verdict": verdict,
        "score_breakdown": {"final_opportunity_score": score},
    }


def test_default_research_capacity_is_wider_without_relaxing_production_threshold():
    assert DEFAULT_RESEARCH_BUCKET_LIMITS["core_dividend"] == 3
    assert DEFAULT_RESEARCH_BUCKET_LIMITS["value_rebound"] == 3
    assert DEFAULT_RESEARCH_BUCKET_LIMITS["news_momentum"] == 2
    assert DEFAULT_RESEARCH_BUCKET_LIMITS[EXPLORATORY_BUCKET] == 2
    assert AUTO_CLASSIFY_THRESHOLD > 0.60


def test_near_classified_candidate_enters_exploratory_research_only(monkeypatch):
    monkeypatch.setenv("BACKTEST_RESEARCH_EXPLORATORY_MIN_CONFIDENCE", "0.60")
    selection = select_research_backtest_candidates(
        [
            _row(
                "NVDA",
                bucket="",
                status="not_classified",
                confidence=0.68,
            )
        ],
        min_final_score=0.55,
    )

    assert selection["selected_count"] == 1
    candidate = selection["selected"][0]
    assert candidate["symbol"] == "NVDA"
    assert candidate["strategy_bucket"] == EXPLORATORY_BUCKET
    assert candidate["selection_lane"] == "research_strategy_discovery"
    assert candidate["research_strategy_discovery"] is True
    assert candidate["production_entry_authorized"] is False
    assert candidate["risk_execution_authorized"] is False
    assert selection["exploratory_policy"]["broker_order_authorized"] is False
    assert selection["exploratory_policy"][
        "production_auto_classify_threshold_unchanged"
    ] is True


def test_low_confidence_unclassified_candidate_stays_blocked(monkeypatch):
    monkeypatch.setenv("BACKTEST_RESEARCH_EXPLORATORY_MIN_CONFIDENCE", "0.60")
    selection = select_research_backtest_candidates(
        [
            _row(
                "WEAK",
                bucket="",
                status="not_classified",
                confidence=0.40,
            )
        ],
        min_final_score=0.55,
    )

    assert selection["selected_count"] == 0
    evaluation = selection["evaluations"][0]
    assert evaluation["eligible"] is False
    assert "bucket_not_classified" in evaluation["reasons"]


def test_wider_bucket_limit_can_select_three_value_rebound_candidates():
    selection = select_research_backtest_candidates(
        [
            _row("AAA", score=0.69),
            _row("BBB", score=0.68),
            _row("CCC", score=0.67),
            _row("DDD", score=0.66),
        ],
        min_final_score=0.55,
    )

    assert [item["symbol"] for item in selection["selected"]] == [
        "AAA",
        "BBB",
        "CCC",
    ]
    assert all(
        item["production_entry_authorized"] is False
        for item in selection["selected"]
    )

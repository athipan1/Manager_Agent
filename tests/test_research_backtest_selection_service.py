from app.services.research_backtest_selection_service import (
    select_research_backtest_candidates,
)


def _row(
    symbol: str,
    *,
    score: float = 0.60,
    verdict: str = "hold",
    bucket: str = "value_rebound",
    confidence: float = 0.80,
    evidence_gate_passed: bool = True,
    fail_closed: bool = False,
):
    return {
        "symbol": symbol,
        "strategy_bucket": bucket,
        "bucket_confidence": confidence,
        "bucket_classification_status": "classified",
        "evidence_gate_passed": evidence_gate_passed,
        "final_verdict": verdict,
        "score_breakdown": {"final_opportunity_score": score},
        "scanner_candidate": {
            "metadata": {
                "details": {
                    "data_bundle": {
                        "opportunity_profile": {"fail_closed": fail_closed}
                    }
                }
            }
        },
    }


def test_hold_candidate_can_reach_research_backtest_without_trade_authority():
    selection = select_research_backtest_candidates(
        [_row("SMCI", score=0.5942, verdict="hold")],
        min_final_score=0.58,
    )

    assert [row["symbol"] for row in selection["selected"]] == ["SMCI"]
    assert selection["selected"][0]["production_entry_authorized"] is False
    assert selection["selected"][0]["risk_execution_authorized"] is False


def test_sell_candidate_is_not_research_eligible():
    selection = select_research_backtest_candidates(
        [_row("SELLME", verdict="sell", score=0.90)],
        min_final_score=0.58,
    )

    assert selection["selected"] == []
    assert selection["evaluations"][0]["eligible"] is False
    assert "verdict_not_research_eligible:sell" in selection["evaluations"][0]["reasons"]


def test_explicit_scanner_fail_closed_stays_blocked():
    selection = select_research_backtest_candidates(
        [_row("BLOCK", verdict="buy", score=0.90, fail_closed=True)],
        min_final_score=0.58,
    )

    assert selection["selected"] == []
    assert "scanner_opportunity_fail_closed" in selection["evaluations"][0]["reasons"]


def test_research_selector_keeps_score_classification_and_evidence_gates():
    rows = [
        _row("LOW_SCORE", score=0.57),
        _row("LOW_CONF", score=0.80, confidence=0.69),
        _row("BAD_EVIDENCE", score=0.80, evidence_gate_passed=False),
        _row("PASS", score=0.80),
    ]

    selection = select_research_backtest_candidates(rows, min_final_score=0.58)

    assert [row["symbol"] for row in selection["selected"]] == ["PASS"]


def test_research_selector_respects_bucket_limits_and_score_order():
    rows = [
        _row("VALUE1", score=0.70),
        _row("VALUE2", score=0.80),
        _row("VALUE3", score=0.90),
    ]

    selection = select_research_backtest_candidates(rows, min_final_score=0.58)

    assert [row["symbol"] for row in selection["selected"]] == ["VALUE3", "VALUE2"]

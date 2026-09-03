from app.services.research_backtest_selection_service import (
    EXPLORATORY_BUCKET,
    RESEARCH_RERANKER_VERSION,
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
    candidate_score: float | None = None,
    hard_gates_passed: int = 0,
    reward_risk: float | None = None,
):
    candidate_score_v1 = None
    if candidate_score is not None:
        gates = {
            f"gate_{index}": index < hard_gates_passed
            for index in range(6)
        }
        candidate_score_v1 = {
            "score_version": "candidate-score.v1",
            "score": candidate_score,
            "max_score": 10,
            "hard_gates": gates,
            "criteria": {
                "opportunity": {
                    "reward_risk": reward_risk,
                }
            },
            "evidence_coverage": {
                "fundamental": 1.0,
                "technical": 1.0,
                "scanner_analysis": 1.0,
            },
        }
    return {
        "symbol": symbol,
        "strategy_bucket": bucket,
        "bucket_confidence": confidence,
        "bucket_classification_status": "classified",
        "evidence_gate_passed": evidence_gate_passed,
        "final_verdict": verdict,
        "score_breakdown": {
            "final_opportunity_score": score,
            "candidate_score_v1": candidate_score_v1,
        },
        "candidate_score_v1": candidate_score_v1,
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


def test_research_selector_keeps_score_and_evidence_gates_and_isolates_near_classification():
    rows = [
        _row("LOW_SCORE", score=0.57),
        _row("LOW_CONF", score=0.80, confidence=0.69),
        _row("BAD_EVIDENCE", score=0.80, evidence_gate_passed=False),
        _row("PASS", score=0.80),
    ]

    selection = select_research_backtest_candidates(rows, min_final_score=0.58)

    assert [row["symbol"] for row in selection["selected"]] == ["PASS", "LOW_CONF"]
    low_conf = next(row for row in selection["selected"] if row["symbol"] == "LOW_CONF")
    assert low_conf["strategy_bucket"] == EXPLORATORY_BUCKET
    assert low_conf["selection_lane"] == "research_strategy_discovery"
    assert low_conf["production_entry_authorized"] is False
    assert low_conf["risk_execution_authorized"] is False


def test_legacy_rows_keep_final_score_order_with_wider_research_capacity():
    rows = [
        _row("VALUE1", score=0.70),
        _row("VALUE2", score=0.80),
        _row("VALUE3", score=0.90),
    ]

    selection = select_research_backtest_candidates(rows, min_final_score=0.58)

    assert [row["symbol"] for row in selection["selected"]] == [
        "VALUE3",
        "VALUE2",
        "VALUE1",
    ]


def test_candidate_score_reranks_wider_backtest_slots_before_final_score():
    rows = [
        _row(
            "HIGH_FINAL_LOW_EVIDENCE",
            score=0.90,
            candidate_score=5,
            hard_gates_passed=2,
            reward_risk=0.8,
        ),
        _row(
            "LOWER_FINAL_HIGH_EVIDENCE",
            score=0.62,
            candidate_score=8,
            hard_gates_passed=5,
            reward_risk=2.4,
        ),
        _row(
            "MID_FINAL_GOOD_EVIDENCE",
            score=0.70,
            candidate_score=7,
            hard_gates_passed=4,
            reward_risk=2.0,
        ),
    ]

    selection = select_research_backtest_candidates(rows, min_final_score=0.58)

    assert [row["symbol"] for row in selection["selected"]] == [
        "LOWER_FINAL_HIGH_EVIDENCE",
        "MID_FINAL_GOOD_EVIDENCE",
        "HIGH_FINAL_LOW_EVIDENCE",
    ]
    assert selection["reranker_version"] == RESEARCH_RERANKER_VERSION
    assert selection["reranker_policy"]["candidate_score_is_ordering_only"] is True
    assert selection["reranker_policy"]["production_binding"] is False
    assert selection["reranker_policy"]["thresholds_relaxed"] is False


def test_reranker_evidence_is_persisted_for_audit():
    selection = select_research_backtest_candidates(
        [
            _row(
                "AUDIT",
                score=0.65,
                candidate_score=8,
                hard_gates_passed=4,
                reward_risk=2.2,
            )
        ],
        min_final_score=0.58,
    )

    evidence = selection["selected"][0]["research_reranker"]
    assert evidence["reranker_version"] == RESEARCH_RERANKER_VERSION
    assert evidence["candidate_score"] == 8
    assert evidence["candidate_hard_gates_passed"] == 4
    assert evidence["reward_risk"] == 2.2
    assert evidence["ordering_only"] is True
    assert evidence["production_binding"] is False

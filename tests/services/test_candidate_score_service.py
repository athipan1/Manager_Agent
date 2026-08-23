from app.services.candidate_score_service import build_candidate_score_v1


def _analysis(*, resistance=115.0):
    fundamental_criteria = {
        name: {
            "available": True,
            "passed": True,
            "point": 1,
            "observed": 1,
            "threshold": "test",
            "source": "fundamental-agent",
        }
        for name in (
            "revenue_growth",
            "eps_growth",
            "free_cash_flow",
            "debt_quality",
            "capital_efficiency",
        )
    }
    return {
        "raw_data": {
            "fundamental": {
                "data": {
                    "evidence_status": "complete",
                    "fundamental_evidence": {
                        "evidence_status": "complete",
                        "provenance": {
                            "candidate_scorecard": {
                                "score_version": "candidate-score.v1",
                                "criteria": fundamental_criteria,
                            }
                        },
                    },
                }
            },
            "technical": {
                "data": {
                    "current_price": 100.0,
                    "evidence_status": "complete",
                    "indicators": {"stop_loss": 95.0},
                    "technical_evidence": {
                        "evidence_status": "complete",
                        "metrics": {
                            "current_price": 100.0,
                            "stop_loss": 95.0,
                            "resistance_level": resistance,
                            "volume_ratio": 1.5,
                        },
                        "provenance": {},
                    },
                }
            },
        }
    }


def _scanner_candidate(*, opportunity_status="qualified", fail_closed=False):
    return {
        "metadata": {
            "details": {
                "data_bundle": {
                    "technical": {
                        "indicator_values": {
                            "close": 100.0,
                            "sma50": 96.0,
                            "sma200": 90.0,
                        }
                    },
                    "market_rank": {
                        "market_rank_score": 0.80,
                        "return_20d": 0.08,
                        "return_60d": 0.20,
                        "volume_ratio": 1.5,
                        "trend_score": 0.9,
                    },
                    "opportunity_profile": {
                        "schema_version": "scanner-opportunity-profile.v1",
                        "status": opportunity_status,
                        "workflow_status": "ready",
                        "opportunity_score": 0.84,
                        "fail_closed": fail_closed,
                        "execution_context": {
                            "current_price": 100.0,
                            "relative_volume": 1.5,
                            "spread_bps": 5.0,
                            "atr_pct": 0.02,
                        },
                    },
                    "data_quality": {
                        "analysis": {
                            "status": "complete",
                            "coverage_ratio": 1.0,
                        }
                    },
                }
            }
        }
    }


def test_candidate_score_v1_builds_ten_points_but_has_no_execution_authority():
    result = build_candidate_score_v1(_analysis(), _scanner_candidate())

    assert result["score_version"] == "candidate-score.v1"
    assert result["fundamental_points"] == 5
    assert result["technical_points"] == 4
    assert result["opportunity_points"] == 1
    assert result["score"] == 10
    assert result["criteria"]["opportunity"]["reward_risk"] == 3.0
    assert result["hard_gates_passed"] is True
    assert result["decision"] == "CANDIDATE"
    assert result["activation_mode"] == "shadow_observation"
    assert result["production_binding"] is False
    assert result["risk_approval_required"] is True
    assert result["execution_authority"] is False


def test_high_score_with_bad_reward_risk_is_review_not_candidate():
    result = build_candidate_score_v1(
        _analysis(resistance=106.0),
        _scanner_candidate(),
    )

    assert result["fundamental_points"] == 5
    assert result["technical_points"] == 4
    assert result["opportunity_points"] == 0
    assert result["score"] == 9
    assert result["hard_gates"]["reward_risk_at_least_2"] is False
    assert result["hard_gates_passed"] is False
    assert result["decision"] == "REVIEW"


def test_scanner_fail_closed_blocks_candidate_even_with_ten_point_setup():
    result = build_candidate_score_v1(
        _analysis(),
        _scanner_candidate(opportunity_status="avoid", fail_closed=True),
    )

    assert result["score"] == 10
    assert result["hard_gates"]["scanner_opportunity_qualified"] is False
    assert result["hard_gates_passed"] is False
    assert result["decision"] == "REVIEW"


def test_missing_scanner_market_evidence_gets_no_synthetic_technical_points():
    result = build_candidate_score_v1(
        _analysis(),
        {
            "metadata": {
                "details": {
                    "data_bundle": {
                        "technical": {"indicator_values": {"close": 100.0}},
                        "market_rank": {},
                        "opportunity_profile": {
                            "status": "review",
                            "fail_closed": False,
                            "execution_context": {},
                        },
                        "data_quality": {
                            "analysis": {
                                "status": "partial",
                                "coverage_ratio": 0.5,
                            }
                        },
                    }
                }
            }
        },
    )

    assert result["technical_points"] == 1
    assert result["evidence_coverage"]["technical"] == 0.25
    assert result["hard_gates"]["technical_evidence_usable"] is False
    assert result["hard_gates"]["scanner_analysis_coverage"] is False
    assert result["decision"] != "CANDIDATE"

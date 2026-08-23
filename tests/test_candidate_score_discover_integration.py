from app.discover_allocation import enrich_ranked_candidates_with_buckets


def _ranked_item():
    criteria = {
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
        "symbol": "AAPL",
        "analysis": {
            "ticker": "AAPL",
            "final_verdict": "buy",
            "status": "complete",
            "raw_data": {
                "fundamental": {
                    "data": {
                        "fundamental_evidence": {
                            "evidence_status": "complete",
                            "provenance": {
                                "candidate_scorecard": {"criteria": criteria}
                            },
                        }
                    }
                },
                "technical": {
                    "data": {
                        "current_price": 100.0,
                        "indicators": {"stop_loss": 95.0},
                        "technical_evidence": {
                            "evidence_status": "complete",
                            "metrics": {
                                "current_price": 100.0,
                                "stop_loss": 95.0,
                                "resistance_level": 115.0,
                                "volume_ratio": 1.5,
                            },
                        },
                    }
                },
            },
        },
        "scanner_candidate": {
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
                            "market_rank_score": 0.8,
                            "return_20d": 0.08,
                            "return_60d": 0.20,
                            "volume_ratio": 1.5,
                        },
                        "opportunity_profile": {
                            "status": "qualified",
                            "opportunity_score": 0.82,
                            "fail_closed": False,
                            "execution_context": {"relative_volume": 1.5},
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
        },
        "score_breakdown": {"final_opportunity_score": 0.73},
        "strategy_bucket_classification": {
            "bucket": "core_dividend",
            "proposed_bucket": "core_dividend",
            "confidence": 0.9,
            "status": "classified",
            "allows_new_entry": True,
            "evidence_gate_passed": True,
            "reasons": [],
            "classifier_version": "manager-strategy-bucket-v3",
            "evidence_summary": {},
        },
    }


def test_discovery_attaches_candidate_score_without_changing_legacy_rank_score():
    ranked = [_ranked_item()]

    enriched = enrich_ranked_candidates_with_buckets(ranked)

    score = enriched[0]["candidate_score_v1"]
    assert score["score"] == 10
    assert score["decision"] == "CANDIDATE"
    assert score["production_binding"] is False
    assert enriched[0]["score_breakdown"]["final_opportunity_score"] == 0.73
    assert enriched[0]["score_breakdown"]["candidate_score_v1"]["score"] == 10
    assert ranked[0]["score_breakdown"]["final_opportunity_score"] == 0.73
    assert ranked[0]["score_breakdown"]["candidate_score_v1"]["score"] == 10

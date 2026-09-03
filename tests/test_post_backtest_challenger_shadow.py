from scripts.run_post_backtest_challenger_shadow import build_post_backtest_candidates


def _scanner():
    return {
        "response": {
            "data": {
                "ranked_candidates": [
                    {
                        "symbol": "TCOM",
                        "metadata": {
                            "details": {
                                "data_bundle": {
                                    "opportunity_profile": {
                                        "status": "qualified",
                                        "opportunity_score": 0.90,
                                        "preferred_strategy_hint": "breakout",
                                        "strategy_affinity": {"sma_crossover": 0.8},
                                        "execution_context": {
                                            "current_price": 210.0,
                                            "quote_status": "fresh",
                                            "market_session": "regular",
                                        },
                                        "evidence_quality": {"coverage": 1.0},
                                    }
                                }
                            }
                        },
                    }
                ]
            }
        }
    }


def test_backtest_challenger_is_reintroduced_to_shadow_with_exact_strategy():
    candidates = build_post_backtest_candidates(
        _scanner(),
        {
            "items": [
                {
                    "symbol": "TCOM",
                    "challenger_observation_enabled": True,
                    "best_strategy_name": "sma_crossover",
                    "failed_candidate_oos_gates": [
                        "candidate_oos_median_sharpe_ratio"
                    ],
                }
            ]
        },
    )
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["symbol"] == "TCOM"
    assert candidate["preferred_strategy_hint"] == "sma_crossover"
    assert candidate["metadata"]["backtest_challenger"]["broker_order_authorized"] is False


def test_non_challenger_is_not_reintroduced_to_shadow():
    candidates = build_post_backtest_candidates(
        _scanner(),
        {
            "items": [
                {
                    "symbol": "TCOM",
                    "challenger_observation_enabled": False,
                    "best_strategy_name": "sma_crossover",
                }
            ]
        },
    )
    assert candidates == []


def test_stale_quote_blocks_post_backtest_shadow_candidate():
    scanner = _scanner()
    profile = scanner["response"]["data"]["ranked_candidates"][0]["metadata"]["details"]["data_bundle"]["opportunity_profile"]
    profile["execution_context"]["quote_status"] = "stale_quote"
    candidates = build_post_backtest_candidates(
        scanner,
        {
            "items": [
                {
                    "symbol": "TCOM",
                    "challenger_observation_enabled": True,
                    "best_strategy_name": "sma_crossover",
                }
            ]
        },
    )
    assert candidates == []

from scripts.run_scanner_preselection import extract_backtest_symbols


def _ranked(symbol: str, *, verdict: str, score: float, fail_closed: bool = False):
    return {
        "symbol": symbol,
        "strategy_bucket": "value_rebound",
        "bucket_confidence": 0.80,
        "bucket_classification_status": "classified",
        "evidence_gate_passed": True,
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


def test_ranked_hold_candidate_reaches_backtest_even_when_production_selection_is_empty():
    response = {
        "status": "success",
        "data": {
            "bucket_selection": {"summary": {"min_final_score": 0.58}},
            "pre_backtest_selected_positions": [],
            "ranked_candidates": [
                _ranked("SMCI", verdict="hold", score=0.5942),
                _ranked("BSX", verdict="hold", score=0.5940),
            ],
        },
    }

    assert extract_backtest_symbols(response) == ["SMCI", "BSX"]
    research = response["data"]["research_backtest_selection"]
    assert research["selected_count"] == 2
    assert research["production_entry_authorized"] is False
    assert research["risk_execution_authorized"] is False


def test_ranked_sell_and_fail_closed_candidates_never_reach_backtest():
    response = {
        "status": "success",
        "data": {
            "bucket_selection": {"summary": {"min_final_score": 0.58}},
            "pre_backtest_selected_positions": [{"symbol": "LEGACY"}],
            "ranked_candidates": [
                _ranked("SELLME", verdict="sell", score=0.90),
                _ranked("BLOCK", verdict="buy", score=0.90, fail_closed=True),
            ],
        },
    }

    assert extract_backtest_symbols(response) == []
    reasons = {
        row["symbol"]: row["reasons"]
        for row in response["data"]["research_backtest_selection"]["evaluations"]
    }
    assert "verdict_not_research_eligible:sell" in reasons["SELLME"]
    assert "scanner_opportunity_fail_closed" in reasons["BLOCK"]


def test_legacy_response_without_ranked_rows_keeps_existing_fallback():
    response = {
        "status": "success",
        "data": {
            "pre_backtest_selected_positions": [
                {"symbol": "AAPL"},
                {"ticker": "MSFT"},
            ]
        },
    }

    assert extract_backtest_symbols(response) == ["AAPL", "MSFT"]

from app.stock_risk_context import build_stock_risk_context


def test_build_stock_risk_context_includes_portfolio_allocation_metadata():
    analysis_result = {
        "ticker": "KO",
        "strategy_bucket": "core_dividend",
        "portfolio_context": {
            "target_weight": 0.5,
            "allocation_pct": 50.0,
            "target_value": 50000.0,
            "suggested_max_value": 10000.0,
            "suggested_equal_weight_value": 25000.0,
        },
        "scanner_candidate": {
            "metadata": {"sector": "Consumer Defensive"},
        },
        "score_breakdown": {"final_opportunity_score": 0.8},
    }

    context = build_stock_risk_context("KO", positions=[], analysis_result=analysis_result)

    assert context["strategy_bucket"] == "core_dividend"
    assert context["target_weight"] == 0.5
    assert context["allocation_pct"] == 50.0
    assert context["target_value"] == 50000.0
    assert context["suggested_max_value"] == 10000.0
    assert context["suggested_equal_weight_value"] == 25000.0

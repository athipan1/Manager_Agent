from app.stock_risk_context import build_stock_risk_context


def test_build_stock_risk_context_includes_strategy_bucket_from_analysis_tags():
    analysis = {
        "ticker": "NEWS",
        "final_verdict": "buy",
        "score_breakdown": {"final_opportunity_score": 0.72},
        "scanner_candidate": {
            "metadata": {"tags": ["news", "catalyst"]},
            "raw_scores": {},
        },
    }

    context = build_stock_risk_context("NEWS", [], analysis)

    assert context["strategy_bucket"] == "news_momentum"
    assert context["current_bucket_exposure"] == 0.0


def test_build_stock_risk_context_uses_position_bucket_exposure():
    positions = [
        {
            "symbol": "KO",
            "quantity": 100,
            "current_price": 60,
            "metadata": {"strategy_bucket": "core_dividend", "sector": "consumer defensive"},
        },
        {
            "symbol": "JNJ",
            "quantity": 20,
            "current_price": 150,
            "metadata": {"strategy_bucket": "core_dividend", "sector": "healthcare"},
        },
        {
            "symbol": "NEWS",
            "quantity": 10,
            "current_price": 100,
            "metadata": {"strategy_bucket": "news_momentum"},
        },
    ]
    analysis = {
        "ticker": "PEP",
        "final_verdict": "buy",
        "score_breakdown": {"final_opportunity_score": 0.66},
        "scanner_candidate": {
            "metadata": {"tags": ["dividend"], "sector": "consumer defensive"},
            "raw_scores": {"dividend_yield": 0.03},
        },
    }

    context = build_stock_risk_context("PEP", positions, analysis)

    assert context["strategy_bucket"] == "core_dividend"
    assert context["current_bucket_exposure"] == 9000.0


def test_build_stock_risk_context_falls_back_to_unassigned():
    context = build_stock_risk_context("ACGL", [], {"ticker": "ACGL", "final_verdict": "hold"})

    assert context["strategy_bucket"] in {"value_rebound", "unassigned"}
    assert "current_bucket_exposure" in context

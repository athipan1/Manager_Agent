from decimal import Decimal
from types import SimpleNamespace

from app.bucket_risk_bridge import build_bucket_risk_decisions


def _item(symbol, score, bucket_hint, verdict="buy", price="100"):
    tags = []
    raw_scores = {}
    if bucket_hint == "core_dividend":
        tags = ["dividend"]
    elif bucket_hint == "news_momentum":
        tags = ["news"]
    else:
        raw_scores = {"pe_ratio": 12}
    return {
        "symbol": symbol,
        "analysis": {
            "ticker": symbol,
            "final_verdict": verdict,
            "status": "complete",
            "details": {},
            "raw_data": {
                "technical": {
                    "data": {
                        "current_price": price,
                        "indicators": {"stop_loss": "95"},
                    }
                }
            },
        },
        "scanner_candidate": {"metadata": {"tags": tags}, "raw_scores": raw_scores},
        "score_breakdown": {"final_opportunity_score": score},
    }


def test_bucket_risk_bridge_calls_assess_trade_for_selected_candidates():
    ranked = [
        _item("KO", 0.80, "core_dividend"),
        _item("JNJ", 0.75, "core_dividend"),
        _item("ACGL", 0.82, "value_rebound"),
        _item("ADBE", 0.78, "value_rebound"),
        _item("NEWS1", 0.90, "news_momentum"),
    ]
    calls = []

    def fake_assess_trade(**kwargs):
        calls.append(kwargs)
        return {"approved": True, "symbol": kwargs["symbol"], "position_size": 1}

    result = build_bucket_risk_decisions(
        ranked=ranked,
        portfolio_value=Decimal("100000"),
        positions=[],
        open_orders_exposure=Decimal("0"),
        session_context={"trades_today": 0},
        min_final_score=0.55,
        assess_trade_fn=fake_assess_trade,
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.05"),
        enable_technical_stop=True,
        max_position_pct=Decimal("0.10"),
        margin_multiplier=Decimal("1"),
    )

    assert result["summary"]["risk_checks_attempted"] == 5
    assert result["summary"]["approved_count"] == 5
    assert [call["stock_risk_context"]["strategy_bucket"] for call in calls] == [
        "core_dividend",
        "core_dividend",
        "value_rebound",
        "value_rebound",
        "news_momentum",
    ]
    assert result["bucket_risk_decisions"]["news_momentum"][0]["symbol"] == "NEWS1"


def test_bucket_risk_bridge_respects_max_checks():
    ranked = [
        _item("KO", 0.80, "core_dividend"),
        _item("JNJ", 0.75, "core_dividend"),
        _item("ACGL", 0.82, "value_rebound"),
    ]
    calls = []

    def fake_assess_trade(**kwargs):
        calls.append(kwargs)
        return {"approved": True, "symbol": kwargs["symbol"], "position_size": 1}

    result = build_bucket_risk_decisions(
        ranked=ranked,
        portfolio_value=Decimal("100000"),
        positions=[],
        open_orders_exposure=Decimal("0"),
        session_context={},
        min_final_score=0.55,
        assess_trade_fn=fake_assess_trade,
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.05"),
        enable_technical_stop=True,
        max_position_pct=Decimal("0.10"),
        margin_multiplier=Decimal("1"),
        max_checks=1,
    )

    assert len(calls) == 1
    assert result["summary"]["risk_checks_attempted"] == 1
    skipped = result["bucket_risk_decisions"]["core_dividend"][1]
    assert skipped["status"] == "skipped"
    assert skipped["reason"] == "max risk checks reached"


def test_bucket_risk_bridge_skips_missing_price():
    ranked = [_item("KO", 0.80, "core_dividend", price="0")]

    def fake_assess_trade(**kwargs):
        raise AssertionError("assess_trade should not be called without a price")

    result = build_bucket_risk_decisions(
        ranked=ranked,
        portfolio_value=Decimal("100000"),
        positions=[],
        open_orders_exposure=Decimal("0"),
        session_context={},
        min_final_score=0.55,
        assess_trade_fn=fake_assess_trade,
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.05"),
        enable_technical_stop=True,
        max_position_pct=Decimal("0.10"),
        margin_multiplier=Decimal("1"),
    )

    decision = result["bucket_risk_decisions"]["core_dividend"][0]
    assert decision["status"] == "not_attempted"
    assert decision["reason"] == "missing entry price for risk check"

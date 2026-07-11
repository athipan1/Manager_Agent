from decimal import Decimal
from types import SimpleNamespace

from app.bucket_risk_bridge import build_bucket_risk_decisions


def _item(symbol="KO", score=0.80, bucket="core_dividend"):
    tags = ["dividend"] if bucket == "core_dividend" else []
    raw_scores = {"pe_ratio": 12} if bucket == "value_rebound" else {}
    return {
        "symbol": symbol,
        "analysis": {
            "ticker": symbol,
            "final_verdict": "buy",
            "status": "complete",
            "raw_data": {
                "technical": {
                    "data": {
                        "current_price": "100",
                        "indicators": {"stop_loss": "95"},
                    }
                }
            },
        },
        "scanner_candidate": {
            "metadata": {"tags": tags},
            "raw_scores": raw_scores,
        },
        "score_breakdown": {"final_opportunity_score": score},
    }


def _kwargs(ranked, positions=None, open_orders=None):
    return {
        "ranked": ranked,
        "portfolio_value": Decimal("100000"),
        "positions": positions or [],
        "open_orders": open_orders or [],
        "open_orders_exposure": Decimal("0"),
        "session_context": {},
        "min_final_score": 0.55,
        "assess_trade_fn": lambda **kwargs: {
            "approved": True,
            "symbol": kwargs["symbol"],
        },
        "risk_per_trade": Decimal("0.01"),
        "fixed_stop_loss_pct": Decimal("0.05"),
        "enable_technical_stop": True,
        "max_position_pct": Decimal("0.10"),
        "margin_multiplier": Decimal("1"),
    }


def test_bucket_risk_bridge_blocks_risk_calls_when_existing_position_unprotected():
    calls = []

    def assess(**kwargs):
        calls.append(kwargs)
        return {"approved": True, "symbol": kwargs["symbol"]}

    kwargs = _kwargs(
        [_item()],
        positions=[
            SimpleNamespace(
                symbol="CINF",
                quantity=86,
                current_market_price=Decimal("179"),
                strategy_bucket="value_rebound",
            )
        ],
    )
    kwargs["assess_trade_fn"] = assess

    result = build_bucket_risk_decisions(**kwargs)

    assert calls == []
    assert result["summary"]["exposure_gate_blocked_count"] == 1
    decision = result["bucket_risk_decisions"]["core_dividend"][0]
    assert decision["status"] == "blocked_by_exposure_gate"
    assert "existing_positions_not_fully_protected" in decision[
        "exposure_gate"
    ]["rejection_codes"]


def test_bucket_risk_bridge_passes_maximum_order_value_to_risk_context():
    captured = {}

    def assess(**kwargs):
        captured.update(kwargs)
        return {"approved": True, "symbol": kwargs["symbol"]}

    kwargs = _kwargs([_item()])
    kwargs["assess_trade_fn"] = assess

    result = build_bucket_risk_decisions(**kwargs)

    assert result["summary"]["risk_checks_attempted"] == 1
    context = captured["stock_risk_context"]
    assert context["maximum_order_value"] == 10000.0
    assert context["exposure_gate"]["allowed"] is True


def test_pending_cancel_buy_order_still_reserves_capacity():
    captured = {}

    def assess(**kwargs):
        captured.update(kwargs)
        return {"approved": True, "symbol": kwargs["symbol"]}

    kwargs = _kwargs(
        [_item(symbol="ACGL", bucket="value_rebound")],
        open_orders=[
            {
                "symbol": "ACGL",
                "strategy_bucket": "value_rebound",
                "side": "buy",
                "type": "limit",
                "qty": 20,
                "limit_price": "100",
                "status": "pending_cancel",
            }
        ],
    )
    kwargs["assess_trade_fn"] = assess

    build_bucket_risk_decisions(**kwargs)

    assert captured["stock_risk_context"]["maximum_order_value"] == 5000.0

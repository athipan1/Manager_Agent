from decimal import Decimal
from types import SimpleNamespace

from app.portfolio_risk_manager import assess_portfolio_trades


def test_portfolio_risk_context_uses_broker_dict_position_quantity(monkeypatch):
    captured = {}

    def fake_assess_trade(**kwargs):
        captured.update(kwargs)
        return {
            "approved": False,
            "reason": "test",
            "symbol": kwargs["symbol"],
            "action": kwargs["action"],
            "entry_price": kwargs["entry_price"],
            "position_size": 0,
            "risk_amount": Decimal("0"),
            "stock_risk_context": kwargs["stock_risk_context"],
        }

    monkeypatch.setattr("app.portfolio_risk_manager.assess_trade", fake_assess_trade)

    positions = [
        {"symbol": "AAPL", "qty": "1", "current_price": "299.92", "market_value": "299.92"},
        {"symbol": "ACGL", "qty": "2190", "avg_entry_price": "91.31", "current_price": "92.34", "market_value": "202224.6", "metadata": {"sector": "Financial Services"}},
    ]
    result = {
        "ticker": "ACGL",
        "final_verdict": "buy",
        "details": SimpleNamespace(technical=SimpleNamespace(score=1.0), fundamental=SimpleNamespace(score=1.0)),
        "raw_data": {
            "technical": {"data": {"current_price": "92.34"}},
            "fundamental": {"data": {"sector": "Financial Services"}},
        },
    }

    decisions = assess_portfolio_trades(
        analysis_results=[result],
        cash_balance=Decimal("-100223.4"),
        existing_positions=positions,
        per_request_risk_budget=Decimal("0.05"),
        max_total_exposure=Decimal("0.50"),
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.03"),
        enable_technical_stop=False,
        max_position_pct=Decimal("0.10"),
        min_position_value=Decimal("500"),
    )

    assert decisions[0]["symbol"] == "ACGL"
    assert captured["current_position_size"] == 2190
    assert captured["current_symbol_exposure"] == Decimal("202224.6")
    assert captured["stock_risk_context"]["owned_quantity"] == 2190.0
    assert captured["stock_risk_context"]["current_symbol_exposure"] == 202224.6

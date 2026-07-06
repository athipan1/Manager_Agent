from decimal import Decimal

from app import risk_manager
from app.database_client import _coerce_dict


def test_assess_trade_uses_request_account_id(monkeypatch):
    captured = {}

    def fake_evaluate_risk(payload):
        captured.update(payload)
        return {
            "status": "approved",
            "data": {
                "approved": True,
                "final_quantity": 1,
                "approved_quantity": 1,
                "guard_plan": {
                    "trigger_price": 90.0,
                    "take_profit_price": 120.0,
                },
            },
        }

    monkeypatch.setattr(risk_manager, "evaluate_risk", fake_evaluate_risk)

    result = risk_manager.assess_trade(
        portfolio_value=Decimal("10000"),
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.1"),
        enable_technical_stop=True,
        max_position_pct=Decimal("0.2"),
        symbol="AAPL",
        action="buy",
        entry_price=Decimal("100"),
        technical_stop_loss=Decimal("90"),
        current_total_exposure=Decimal("0"),
        open_orders_exposure=Decimal("0"),
        account_id=7,
    )

    assert result["approved"] is True
    assert captured["account_id"] == 7


def test_coerce_dict_supports_database_order_execution_response_shape():
    payload = {
        "order_id": 123,
        "trade_id": "trade-1",
        "account_id": "1",
        "status": "executed",
        "reason": None,
    }

    assert _coerce_dict(payload) == payload

from decimal import Decimal
from unittest.mock import patch

from app.risk_manager import assess_trade


def ok(qty=5):
    return {
        "status": "approved",
        "data": {
            "approved": True,
            "final_quantity": qty,
            "approved_quantity": qty,
            "guard_plan": {"symbol": "AAPL", "quantity": qty},
            "violations": [],
        },
        "error": None,
    }


@patch("app.risk_manager.config.TRADING_ENABLED", True)
@patch("app.risk_manager.config.TRADING_MODE", "PAPER")
@patch("app.risk_manager.evaluate_risk")
def test_filled_and_waiting_values_stay_separate(mock_eval):
    mock_eval.return_value = ok(5)

    assess_trade(
        portfolio_value=Decimal("100000"),
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.10"),
        enable_technical_stop=True,
        max_position_pct=Decimal("0.20"),
        symbol="AAPL",
        action="buy",
        entry_price=Decimal("150"),
        technical_stop_loss=Decimal("140"),
        current_position_size=250,
        current_symbol_exposure=Decimal("500"),
        current_total_exposure=Decimal("1000"),
        open_orders_exposure=Decimal("200"),
        requested_quantity=5,
    )

    payload = mock_eval.call_args.args[0]
    assert payload["current_symbol_exposure"] == 500.0
    assert payload["current_total_exposure"] == 1000.0
    assert payload["open_orders_exposure"] == 200.0
    assert payload["requested_quantity"] == 5


@patch("app.risk_manager.config.TRADING_ENABLED", True)
@patch("app.risk_manager.config.TRADING_MODE", "PAPER")
@patch("app.risk_manager.evaluate_risk")
def test_buy_size_is_derived_from_new_request_not_existing_position(mock_eval):
    mock_eval.return_value = ok(1)

    assess_trade(
        portfolio_value=Decimal("100000"),
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.10"),
        enable_technical_stop=True,
        max_position_pct=Decimal("0.20"),
        symbol="AAPL",
        action="buy",
        entry_price=Decimal("150"),
        technical_stop_loss=Decimal("140"),
        current_position_size=250,
    )

    payload = mock_eval.call_args.args[0]
    assert payload["requested_quantity"] == 100
    assert payload["requested_quantity"] != 250


def test_gate_stops_when_disabled():
    with patch("app.risk_manager.config.TRADING_ENABLED", False), patch("app.risk_manager.evaluate_risk") as mock_eval:
        result = assess_trade(
            portfolio_value=Decimal("100000"),
            risk_per_trade=Decimal("0.01"),
            fixed_stop_loss_pct=Decimal("0.10"),
            enable_technical_stop=False,
            max_position_pct=Decimal("0.20"),
            symbol="AAPL",
            action="buy",
            entry_price=Decimal("150"),
        )

    assert result["approved"] is False
    mock_eval.assert_not_called()


def test_hold_does_not_call_external_gate():
    with patch("app.risk_manager.evaluate_risk") as mock_eval:
        result = assess_trade(
            portfolio_value=Decimal("100000"),
            risk_per_trade=Decimal("0.01"),
            fixed_stop_loss_pct=Decimal("0.10"),
            enable_technical_stop=False,
            max_position_pct=Decimal("0.20"),
            symbol="AAPL",
            action="hold",
            entry_price=Decimal("150"),
        )

    assert result["approved"] is False
    mock_eval.assert_not_called()

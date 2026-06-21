from decimal import Decimal
from unittest.mock import patch

from app.risk_manager import assess_trade


def approved_response(quantity=100, symbol="AAPL"):
    return {
        "status": "approved",
        "data": {
            "approved": True,
            "final_quantity": quantity,
            "approved_quantity": quantity,
            "guard_plan": {
                "symbol": symbol,
                "quantity": quantity,
                "trigger_price": 140.0,
            },
            "violations": [],
            "warnings": [],
        },
        "error": None,
    }


@patch("app.risk_manager.config.TRADING_ENABLED", True)
@patch("app.risk_manager.config.TRADING_MODE", "PAPER")
@patch("app.risk_manager.evaluate_risk")
def test_approve_buy_order_fixed_stop(mock_evaluate_risk):
    mock_evaluate_risk.return_value = approved_response(quantity=133, symbol="AAPL")

    decision = assess_trade(
        portfolio_value=Decimal("100000"),
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.05"),
        enable_technical_stop=False,
        max_position_pct=Decimal("0.20"),
        symbol="AAPL",
        action="buy",
        entry_price=Decimal("150.00"),
        current_position_size=200,
    )

    assert decision["approved"] is True
    assert decision["position_size"] == 133
    assert decision["stop_loss"] == Decimal("142.5000")
    assert decision["reason"] == "Approved by external Risk_Agent."

    payload = mock_evaluate_risk.call_args.args[0]
    assert payload["side"] == "buy"
    assert payload["requested_quantity"] == 133
    assert payload["protection_price"] == 142.5
    assert payload["trading_mode"] == "PAPER"


@patch("app.risk_manager.config.TRADING_ENABLED", True)
@patch("app.risk_manager.config.TRADING_MODE", "PAPER")
@patch("app.risk_manager.evaluate_risk")
def test_approve_buy_order_technical_stop(mock_evaluate_risk):
    mock_evaluate_risk.return_value = approved_response(quantity=200, symbol="AAPL")

    decision = assess_trade(
        portfolio_value=Decimal("100000"),
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.05"),
        enable_technical_stop=True,
        max_position_pct=Decimal("0.30"),
        symbol="AAPL",
        action="buy",
        entry_price=Decimal("150.00"),
        technical_stop_loss=Decimal("145.00"),
        current_position_size=250,
    )

    assert decision["approved"] is True
    assert decision["position_size"] == 200
    assert decision["stop_loss"] == Decimal("145.00")
    payload = mock_evaluate_risk.call_args.args[0]
    assert payload["protection_price"] == 145.0


@patch("app.risk_manager.config.TRADING_ENABLED", True)
@patch("app.risk_manager.config.TRADING_MODE", "PAPER")
@patch("app.risk_manager.evaluate_risk")
def test_invalid_buy_technical_stop_falls_back_to_fixed_stop(mock_evaluate_risk):
    mock_evaluate_risk.return_value = approved_response(quantity=100, symbol="AAPL")

    decision = assess_trade(
        portfolio_value=Decimal("100000"),
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.05"),
        enable_technical_stop=True,
        max_position_pct=Decimal("0.20"),
        symbol="AAPL",
        action="buy",
        entry_price=Decimal("150.00"),
        technical_stop_loss=Decimal("151.00"),
        current_position_size=100,
    )

    assert decision["approved"] is True
    assert decision["stop_loss"] == Decimal("142.5000")
    payload = mock_evaluate_risk.call_args.args[0]
    assert payload["protection_price"] == 142.5


@patch("app.risk_manager.config.TRADING_ENABLED", True)
@patch("app.risk_manager.config.TRADING_MODE", "PAPER")
@patch("app.risk_manager.evaluate_risk")
def test_reject_when_external_risk_agent_rejects(mock_evaluate_risk):
    mock_evaluate_risk.return_value = {
        "status": "rejected",
        "data": {
            "approved": False,
            "violations": ["position_size_limit_exceeded"],
        },
        "error": "risk_check_failed",
    }

    decision = assess_trade(
        portfolio_value=Decimal("10000"),
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.01"),
        enable_technical_stop=False,
        max_position_pct=Decimal("0.10"),
        symbol="AAPL",
        action="buy",
        entry_price=Decimal("150.00"),
        current_position_size=100,
    )

    assert decision["approved"] is False
    assert decision["position_size"] == 0
    assert "Rejected by external Risk_Agent" in decision["reason"]


@patch("app.risk_manager.config.TRADING_ENABLED", True)
@patch("app.risk_manager.config.TRADING_MODE", "PAPER")
@patch("app.risk_manager.evaluate_risk")
def test_approve_sell_order_existing_position(mock_evaluate_risk):
    mock_evaluate_risk.return_value = approved_response(quantity=100, symbol="AAPL")

    decision = assess_trade(
        portfolio_value=Decimal("100000"),
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.05"),
        enable_technical_stop=False,
        max_position_pct=Decimal("0.20"),
        symbol="AAPL",
        action="sell",
        entry_price=Decimal("155.00"),
        current_position_size=100,
    )

    assert decision["approved"] is True
    assert decision["position_size"] == 100
    payload = mock_evaluate_risk.call_args.args[0]
    assert payload["side"] == "sell"
    assert payload["protection_price"] == 162.75


@patch("app.risk_manager.config.TRADING_ENABLED", True)
@patch("app.risk_manager.config.TRADING_MODE", "LIVE")
@patch("app.risk_manager.config.ALLOW_LIVE_TRADING", True)
@patch("app.risk_manager.evaluate_risk")
def test_live_payload_includes_session_risk_context(mock_evaluate_risk):
    mock_evaluate_risk.return_value = approved_response(quantity=10, symbol="AAPL")
    session_context = {
        "daily_realized_pnl": -12.5,
        "weekly_realized_pnl": -20.0,
        "consecutive_losses": 1,
        "trades_today": 2,
        "symbol_trades_today": 1,
        "minutes_since_last_loss": 80,
        "minutes_since_last_symbol_trade": 45,
        "emergency_halt": False,
    }

    decision = assess_trade(
        portfolio_value=Decimal("100000"),
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.05"),
        enable_technical_stop=False,
        max_position_pct=Decimal("0.20"),
        symbol="AAPL",
        action="buy",
        entry_price=Decimal("150.00"),
        current_symbol_exposure=Decimal("0"),
        current_total_exposure=Decimal("0"),
        open_orders_exposure=Decimal("0"),
        margin_multiplier=Decimal("1"),
        session_risk_context=session_context,
    )

    assert decision["approved"] is True
    assert decision["session_risk_context"] == session_context
    payload = mock_evaluate_risk.call_args.args[0]
    assert payload["daily_realized_pnl"] == -12.5
    assert payload["weekly_realized_pnl"] == -20.0
    assert payload["consecutive_losses"] == 1
    assert payload["trades_today"] == 2
    assert payload["symbol_trades_today"] == 1
    assert payload["emergency_halt"] is False


@patch("app.risk_manager.config.TRADING_ENABLED", True)
@patch("app.risk_manager.config.TRADING_MODE", "LIVE")
@patch("app.risk_manager.config.ALLOW_LIVE_TRADING", True)
def test_live_rejects_missing_session_risk_context_before_calling_risk_agent():
    with patch("app.risk_manager.evaluate_risk") as mock_evaluate_risk:
        decision = assess_trade(
            portfolio_value=Decimal("100000"),
            risk_per_trade=Decimal("0.01"),
            fixed_stop_loss_pct=Decimal("0.05"),
            enable_technical_stop=False,
            max_position_pct=Decimal("0.20"),
            symbol="AAPL",
            action="buy",
            entry_price=Decimal("150.00"),
            current_symbol_exposure=Decimal("0"),
            current_total_exposure=Decimal("0"),
            open_orders_exposure=Decimal("0"),
            margin_multiplier=Decimal("1"),
        )

    assert decision["approved"] is False
    assert "LIVE session risk context incomplete" in decision["reason"]
    mock_evaluate_risk.assert_not_called()


def test_reject_invalid_action_without_calling_risk_agent():
    with patch("app.risk_manager.evaluate_risk") as mock_evaluate_risk:
        decision = assess_trade(
            portfolio_value=Decimal("100000"),
            risk_per_trade=Decimal("0.01"),
            fixed_stop_loss_pct=Decimal("0.05"),
            enable_technical_stop=False,
            max_position_pct=Decimal("0.20"),
            symbol="AAPL",
            action="hold",
            entry_price=Decimal("150.00"),
        )

    assert decision["approved"] is False
    assert decision["position_size"] == 0
    assert "skipped" in decision["reason"]
    mock_evaluate_risk.assert_not_called()

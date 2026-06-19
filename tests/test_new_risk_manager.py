from decimal import Decimal
from unittest.mock import patch

from app.risk_manager import assess_trade


def approved_response(final_quantity=100):
    return {
        "status": "approved",
        "data": {
            "approved": True,
            "final_quantity": final_quantity,
            "approved_quantity": final_quantity,
            "guard_plan": {
                "symbol": "AAPL",
                "quantity": final_quantity,
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
def test_assess_trade_approves_with_external_risk_agent(mock_evaluate_risk):
    mock_evaluate_risk.return_value = approved_response(final_quantity=100)

    decision = assess_trade(
        portfolio_value=Decimal("100000"),
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.10"),
        enable_technical_stop=True,
        max_position_pct=Decimal("0.20"),
        symbol="AAPL",
        action="buy",
        entry_price=Decimal("150.00"),
        technical_stop_loss=Decimal("140.00"),
        current_position_size=250,
    )

    assert decision["approved"] is True
    assert decision["position_size"] == 100
    assert decision["stop_loss"] == Decimal("140.00")
    assert decision["guard_plan"]["quantity"] == 100

    payload = mock_evaluate_risk.call_args.args[0]
    assert payload["symbol"] == "AAPL"
    assert payload["side"] == "buy"
    assert payload["entry_price"] == 150.0
    assert payload["protection_price"] == 140.0
    assert payload["requested_quantity"] == 250
    assert payload["trading_mode"] == "PAPER"


@patch("app.risk_manager.config.TRADING_ENABLED", True)
@patch("app.risk_manager.config.TRADING_MODE", "PAPER")
@patch("app.risk_manager.evaluate_risk")
def test_assess_trade_rejects_when_external_risk_agent_rejects(mock_evaluate_risk):
    mock_evaluate_risk.return_value = {
        "status": "rejected",
        "data": {
            "approved": False,
            "violations": ["position_size_limit_exceeded"],
        },
        "error": "risk_check_failed",
    }

    decision = assess_trade(
        portfolio_value=Decimal("100000"),
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.10"),
        enable_technical_stop=False,
        max_position_pct=Decimal("0.20"),
        symbol="AAPL",
        action="buy",
        entry_price=Decimal("150.00"),
        current_position_size=250,
    )

    assert decision["approved"] is False
    assert decision["position_size"] == 0
    assert "Rejected by external Risk_Agent" in decision["reason"]


@patch("app.risk_manager.config.TRADING_ENABLED", True)
@patch("app.risk_manager.config.TRADING_MODE", "PAPER")
@patch("app.risk_manager.evaluate_risk")
def test_assess_trade_uses_default_protection_price(mock_evaluate_risk):
    mock_evaluate_risk.return_value = approved_response(final_quantity=50)

    decision = assess_trade(
        portfolio_value=Decimal("100000"),
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.10"),
        enable_technical_stop=False,
        max_position_pct=Decimal("0.20"),
        symbol="AAPL",
        action="buy",
        entry_price=Decimal("150.00"),
        current_position_size=100,
    )

    assert decision["approved"] is True
    assert decision["stop_loss"] == Decimal("135.0000")
    payload = mock_evaluate_risk.call_args.args[0]
    assert payload["protection_price"] == 135.0


def test_assess_trade_rejects_when_global_kill_switch_is_off():
    with patch("app.risk_manager.config.TRADING_ENABLED", False), patch("app.risk_manager.evaluate_risk") as mock_evaluate_risk:
        decision = assess_trade(
            portfolio_value=Decimal("100000"),
            risk_per_trade=Decimal("0.01"),
            fixed_stop_loss_pct=Decimal("0.10"),
            enable_technical_stop=False,
            max_position_pct=Decimal("0.20"),
            symbol="AAPL",
            action="buy",
            entry_price=Decimal("150.00"),
            current_position_size=100,
        )

    assert decision["approved"] is False
    assert "TRADING_ENABLED=false" in decision["reason"]
    mock_evaluate_risk.assert_not_called()


def test_assess_trade_rejects_live_when_risk_context_is_incomplete():
    with (
        patch("app.risk_manager.config.TRADING_ENABLED", True),
        patch("app.risk_manager.config.TRADING_MODE", "LIVE"),
        patch("app.risk_manager.config.ALLOW_LIVE_TRADING", True),
        patch("app.risk_manager.evaluate_risk") as mock_evaluate_risk,
    ):
        decision = assess_trade(
            portfolio_value=Decimal("100000"),
            risk_per_trade=Decimal("0.01"),
            fixed_stop_loss_pct=Decimal("0.10"),
            enable_technical_stop=False,
            max_position_pct=Decimal("0.20"),
            symbol="AAPL",
            action="buy",
            entry_price=Decimal("150.00"),
            current_position_size=100,
        )

    assert decision["approved"] is False
    assert "LIVE risk context incomplete" in decision["reason"]
    mock_evaluate_risk.assert_not_called()


def test_assess_trade_rejects_hold_without_calling_risk_agent():
    with patch("app.risk_manager.evaluate_risk") as mock_evaluate_risk:
        decision = assess_trade(
            portfolio_value=Decimal("100000"),
            risk_per_trade=Decimal("0.01"),
            fixed_stop_loss_pct=Decimal("0.10"),
            enable_technical_stop=False,
            max_position_pct=Decimal("0.20"),
            symbol="AAPL",
            action="hold",
            entry_price=Decimal("150.00"),
        )

    assert decision["approved"] is False
    assert decision["position_size"] == 0
    mock_evaluate_risk.assert_not_called()

from decimal import Decimal
from unittest.mock import patch

from app.risk_manager import assess_trade


def _approved_response(quantity=10, symbol="ACGL"):
    return {
        "status": "approved",
        "data": {
            "approved": True,
            "final_quantity": quantity,
            "approved_quantity": quantity,
            "guard_plan": None,
            "violations": [],
            "warnings": [],
        },
        "error": None,
    }


@patch("app.risk_manager.config.TRADING_ENABLED", True)
@patch("app.risk_manager.config.TRADING_MODE", "PAPER")
@patch("app.risk_manager.evaluate_risk")
def test_direct_discover_trade_assess_trade_payload_includes_strategy_bucket(mock_evaluate_risk):
    """/discover-analyze-trade calls assess_trade directly, without build_stock_risk_context()."""
    mock_evaluate_risk.return_value = _approved_response(quantity=10, symbol="ACGL")

    decision = assess_trade(
        portfolio_value=Decimal("100000"),
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.05"),
        enable_technical_stop=False,
        max_position_pct=Decimal("0.20"),
        symbol="ACGL",
        action="buy",
        entry_price=Decimal("100"),
        current_position_size=0,
        current_symbol_exposure=Decimal("0"),
        current_total_exposure=Decimal("0"),
        open_orders_exposure=Decimal("0"),
    )

    assert decision["approved"] is True
    assert decision["stock_risk_context"]["strategy_bucket"] == "value_rebound"
    assert decision["stock_risk_context"]["current_bucket_exposure"] == 0.0

    payload = mock_evaluate_risk.call_args.args[0]
    assert payload["strategy_bucket"] == "value_rebound"
    assert payload["current_bucket_exposure"] == 0.0


@patch("app.risk_manager.config.TRADING_ENABLED", True)
@patch("app.risk_manager.config.TRADING_MODE", "PAPER")
@patch("app.risk_manager.evaluate_risk")
def test_explicit_strategy_bucket_overrides_discover_trade_fallback(mock_evaluate_risk):
    mock_evaluate_risk.return_value = _approved_response(quantity=10, symbol="NEWS")

    decision = assess_trade(
        portfolio_value=Decimal("100000"),
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.05"),
        enable_technical_stop=False,
        max_position_pct=Decimal("0.20"),
        symbol="NEWS",
        action="buy",
        entry_price=Decimal("100"),
        current_position_size=0,
        current_symbol_exposure=Decimal("0"),
        current_total_exposure=Decimal("0"),
        open_orders_exposure=Decimal("0"),
        stock_risk_context={
            "strategy_bucket": "news_momentum",
            "current_bucket_exposure": 1500.0,
        },
    )

    assert decision["approved"] is True
    payload = mock_evaluate_risk.call_args.args[0]
    assert payload["strategy_bucket"] == "news_momentum"
    assert payload["current_bucket_exposure"] == 1500.0

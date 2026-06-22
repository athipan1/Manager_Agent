from decimal import Decimal

from app import config
from app.risk_manager import assess_trade


def test_kill_switch_result_keeps_symbol_and_sector_exposure(monkeypatch):
    monkeypatch.setattr(config, "TRADING_ENABLED", False)

    decision = assess_trade(
        portfolio_value=Decimal("100000"),
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.05"),
        enable_technical_stop=False,
        max_position_pct=Decimal("0.2"),
        symbol="ACGL",
        action="buy",
        entry_price=Decimal("91.98"),
        current_position_size=2190,
        current_symbol_exposure=Decimal("201436.2"),
        current_total_exposure=Decimal("201735.06"),
        open_orders_exposure=Decimal("0"),
    )

    assert decision["approved"] is False
    assert decision["stock_risk_context"]["owned_quantity"] == 2190.0
    assert decision["stock_risk_context"]["current_symbol_exposure"] == 201436.2
    assert decision["stock_risk_context"]["current_sector_exposure"] == 201436.2

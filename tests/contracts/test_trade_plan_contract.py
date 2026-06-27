import pytest
from pydantic import ValidationError

from app.contracts import OrderSide, OrderType, TradePlan, TradePlanExit, TradePlanRisk


def _risk() -> TradePlanRisk:
    return TradePlanRisk(
        account_equity=10000,
        cash_available=5000,
        max_loss_amount=50,
        max_loss_pct=0.005,
        risk_per_share=5,
        position_value=1000,
        position_pct=0.10,
        reward_risk_ratio=2.0,
        session_risk_loaded=True,
        portfolio_context_loaded=True,
    )


def test_trade_plan_normalizes_symbol_and_defaults_final_quantity():
    plan = TradePlan(
        plan_id="plan-1",
        correlation_id="corr-1",
        account_id=1,
        symbol=" aapl ",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        entry_price=100,
        quantity=10,
        strategy="trend_pullback",
        strategy_bucket="value_rebound",
        final_verdict="buy",
        confidence_score=0.67,
        risk=_risk(),
        exit=TradePlanExit(stop_loss=95, take_profit=110),
    )

    assert plan.account_id == "1"
    assert plan.symbol == "AAPL"
    assert plan.final_quantity == 10
    assert plan.manual_approval_required is True


def test_limit_trade_plan_requires_limit_price():
    with pytest.raises(ValidationError, match="limit_price is required"):
        TradePlan(
            plan_id="plan-2",
            correlation_id="corr-2",
            account_id="1",
            symbol="MSFT",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            quantity=5,
            strategy="breakout",
            final_verdict="buy",
            confidence_score=0.60,
            risk=_risk(),
        )


def test_buy_stop_loss_must_be_below_entry_price():
    with pytest.raises(ValidationError, match="buy trade stop_loss"):
        TradePlan(
            plan_id="plan-3",
            correlation_id="corr-3",
            account_id="1",
            symbol="NVDA",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            entry_price=100,
            quantity=2,
            strategy="breakout",
            final_verdict="buy",
            confidence_score=0.61,
            risk=_risk(),
            exit=TradePlanExit(stop_loss=101),
        )


def test_trade_plan_requires_risk_approval_before_execution_order():
    plan = TradePlan(
        plan_id="plan-4",
        correlation_id="corr-4",
        account_id="1",
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        entry_price=100,
        quantity=3,
        strategy="trend_pullback",
        final_verdict="buy",
        confidence_score=0.70,
        risk=_risk(),
        exit=TradePlanExit(stop_loss=95, take_profit=112),
    )

    with pytest.raises(ValueError, match="risk_approval_id is required"):
        plan.to_execution_order()

    plan.risk_approval_id = "risk-123"
    order = plan.to_execution_order()

    assert order.client_order_id == "plan-4"
    assert order.account_id == "1"
    assert order.symbol == "AAPL"
    assert order.risk_approval_id == "risk-123"
    assert order.protective_exit["stop_loss"] == 95

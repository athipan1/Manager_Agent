from decimal import Decimal

from app.contracts import OrderSide, OrderType, TradePlan, TradePlanRisk
from app.routes.web_control import (
    FinanceEntry,
    FinancialAdvisorRequest,
    _find_trade_plan_id,
    _plan_notional,
    build_financial_advice,
    confirmation_phrase,
)


def test_financial_advice_calculates_cash_flow_and_investment_cap():
    request = FinancialAdvisorRequest(
        account_id="acct-1",
        available_investment_capital=Decimal("5000"),
        entries=[
            FinanceEntry(
                entry_type="income",
                amount="30000",
                category="salary",
                occurred_at="2026-07-01T00:00:00Z",
            ),
            FinanceEntry(
                entry_type="expense",
                amount="12000",
                category="housing",
                occurred_at="2026-07-02T00:00:00Z",
            ),
            FinanceEntry(
                entry_type="expense",
                amount="3000",
                category="food",
                occurred_at="2026-07-03T00:00:00Z",
            ),
        ],
    )

    result = build_financial_advice(request)

    assert result["summary"]["net_cash_flow"] == "15000.00"
    assert result["summary"]["suggested_new_investment_cap"] == "3000.00"
    assert result["largest_expense_categories"][0]["category"] == "housing"


def test_confirmation_phrase_includes_runtime_mode(monkeypatch):
    monkeypatch.setattr("app.routes.web_control.config.TRADING_MODE", "paper")
    assert confirmation_phrase("plan-123") == "CONFIRM PAPER plan-123"


def test_find_trade_plan_id_handles_nested_manager_response():
    payload = {"data": {"audit": {"trade_decision": {"trade_plan_id": "plan-nested"}}}}
    assert _find_trade_plan_id(payload) == "plan-nested"


def test_plan_notional_uses_final_quantity():
    plan = TradePlan(
        plan_id="plan-1",
        correlation_id="corr-1",
        source="manual",
        status="risk_approved",
        account_id="1",
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        entry_price=125.50,
        quantity=10,
        final_quantity=8,
        final_verdict="buy",
        confidence_score=0.8,
        risk=TradePlanRisk(max_loss_amount=100, max_loss_pct=0.01),
        risk_approval_id="risk-1",
    )

    assert _plan_notional(plan) == Decimal("1004.0")

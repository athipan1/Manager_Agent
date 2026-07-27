from decimal import Decimal

from app.routes.web_control import (
    FinanceEntry,
    FinancialAdvisorRequest,
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

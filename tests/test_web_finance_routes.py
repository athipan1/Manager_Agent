from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.routes import web_finance
from app.routes.web_finance import (
    PersistedFinancialAdvisorRequest,
    PersistedInvestmentPlanRequest,
    create_investment_plan_from_persisted_limit,
    financial_advisor_from_persisted_state,
)


class DummyDatabaseClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_persisted_investment_plan_uses_database_limit(monkeypatch):
    captured = {}

    async def fake_state(client, account_id, correlation_id):
        return {
            "account_id": account_id,
            "entries": [],
            "budgets": {
                "personal_investment_budget_thb": "5000.00",
                "trade_plan_limit_usd": "250.00",
            },
        }

    async def fake_create(request, _auth, _rate_limit):
        captured["request"] = request
        return {"status": "success", "metadata": {}}

    monkeypatch.setattr(web_finance, "DatabaseAgentClient", DummyDatabaseClient)
    monkeypatch.setattr(web_finance, "_finance_state", fake_state)
    monkeypatch.setattr(web_finance, "create_investment_plan", fake_create)

    result = await create_investment_plan_from_persisted_limit(
        PersistedInvestmentPlanRequest(account_id="1", ticker="aapl", user_goal="controlled plan"),
        None,
        None,
    )

    assert captured["request"].ticker == "AAPL"
    assert captured["request"].max_investment_amount == Decimal("250.00")
    assert captured["request"].investment_currency == "USD"
    assert result["metadata"]["budget_source"] == "database-agent"


@pytest.mark.asyncio
async def test_persisted_investment_plan_blocks_zero_limit(monkeypatch):
    async def fake_state(client, account_id, correlation_id):
        return {"account_id": account_id, "entries": [], "budgets": {"trade_plan_limit_usd": "0"}}

    monkeypatch.setattr(web_finance, "DatabaseAgentClient", DummyDatabaseClient)
    monkeypatch.setattr(web_finance, "_finance_state", fake_state)

    with pytest.raises(HTTPException) as exc_info:
        await create_investment_plan_from_persisted_limit(
            PersistedInvestmentPlanRequest(account_id="1", ticker="AAPL"),
            None,
            None,
        )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_financial_advisor_reads_persisted_entries(monkeypatch):
    async def fake_state(client, account_id, correlation_id):
        return {
            "account_id": account_id,
            "entries": [
                {
                    "entry_type": "income",
                    "amount": "30000.00",
                    "category": "salary",
                    "description": "",
                    "occurred_at": "2026-07-01T00:00:00Z",
                },
                {
                    "entry_type": "expense",
                    "amount": "10000.00",
                    "category": "housing",
                    "description": "",
                    "occurred_at": "2026-07-02T00:00:00Z",
                },
            ],
            "budgets": {"personal_investment_budget_thb": "5000.00", "trade_plan_limit_usd": "250.00"},
        }

    monkeypatch.setattr(web_finance, "DatabaseAgentClient", DummyDatabaseClient)
    monkeypatch.setattr(web_finance, "_finance_state", fake_state)

    result = await financial_advisor_from_persisted_state(
        PersistedFinancialAdvisorRequest(account_id="1", message="สรุปวันนี้"),
        None,
        None,
    )

    assert result["data"]["summary"]["net_cash_flow"] == "20000.00"
    assert result["data"]["summary"]["available_investment_capital"] == "5000.00"
    assert result["metadata"]["source"] == "database-agent"

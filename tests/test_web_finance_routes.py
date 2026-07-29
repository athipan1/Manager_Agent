from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.contracts import OrderSide, OrderType, TradePlan, TradePlanRisk
from app.routes import web_finance
from app.routes.web_finance import (
    PersistedFinancialAdvisorRequest,
    PersistedInvestmentPlanRequest,
    _action_constraint,
    create_investment_plan_from_persisted_limit,
    financial_advisor_from_persisted_state,
)


class DummyDatabaseClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def trade_plan(side=OrderSide.BUY):
    return TradePlan(
        plan_id="plan-1",
        correlation_id="corr-1",
        source="manual",
        status="risk_approved",
        account_id="1",
        symbol="AAPL",
        side=side,
        order_type=OrderType.MARKET,
        entry_price=125.50,
        quantity=2,
        final_quantity=2,
        final_verdict=side.value,
        confidence_score=0.8,
        risk=TradePlanRisk(max_loss_amount=20, max_loss_pct=0.01),
        risk_approval_id="risk-1",
    )


def finance_state(account_id="1", trade_limit="250.00"):
    return {
        "account_id": account_id,
        "entries": [],
        "budgets": {
            "personal_investment_budget_thb": "5000.00",
            "trade_plan_limit_usd": trade_limit,
        },
    }


@pytest.mark.asyncio
async def test_persisted_investment_plan_uses_database_limit(monkeypatch):
    captured = {}

    async def fake_state(client, account_id, correlation_id):
        return finance_state(account_id)

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
    assert result["metadata"]["requested_action"] == "AUTO"


@pytest.mark.asyncio
async def test_persisted_investment_plan_blocks_zero_limit(monkeypatch):
    async def fake_state(client, account_id, correlation_id):
        return finance_state(account_id, trade_limit="0")

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
async def test_buy_plan_is_rejected_when_operator_allows_sell_only(monkeypatch):
    updates = []

    async def fake_state(client, account_id, correlation_id):
        return finance_state(account_id)

    async def fake_create(request, _auth, _rate_limit):
        return {
            "status": "success",
            "metadata": {
                "trade_plan_id": "plan-1",
                "trade_plan_status": "queued",
                "confirmation_ready": True,
            },
        }

    async def fake_get_plan(client, trade_plan_id, correlation_id):
        return {
            "trade_plan_id": trade_plan_id,
            "status": "queued",
            "plan": trade_plan().model_dump(mode="json"),
        }

    async def fake_update(client, trade_plan_id, correlation_id, **kwargs):
        updates.append({"trade_plan_id": trade_plan_id, **kwargs})
        return {"status": kwargs["status_value"]}

    monkeypatch.setattr(web_finance, "DatabaseAgentClient", DummyDatabaseClient)
    monkeypatch.setattr(web_finance, "_finance_state", fake_state)
    monkeypatch.setattr(web_finance, "create_investment_plan", fake_create)
    monkeypatch.setattr(web_finance, "_get_trade_plan", fake_get_plan)
    monkeypatch.setattr(web_finance, "_update_trade_plan_status", fake_update)

    result = await create_investment_plan_from_persisted_limit(
        PersistedInvestmentPlanRequest(
            account_id="1",
            ticker="AAPL",
            requested_action="SELL",
        ),
        None,
        None,
    )

    assert result["metadata"]["confirmation_ready"] is False
    assert result["metadata"]["trade_plan_status"] == "rejected"
    assert result["metadata"]["actual_action"] == "BUY"
    assert updates[0]["status_value"] == "rejected"
    assert updates[0]["expected_status"] == "queued"


def test_action_constraint_accepts_auto_and_matching_direction():
    assert _action_constraint("AUTO", trade_plan(OrderSide.BUY)).matched is True
    assert _action_constraint("BUY", trade_plan(OrderSide.BUY)).matched is True
    assert _action_constraint("SELL", trade_plan(OrderSide.BUY)).matched is False


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

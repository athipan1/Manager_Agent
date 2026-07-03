from decimal import Decimal

import pytest

from app.risk_approval_contract import persist_risk_approval
from app.services.audit_service import dry_run_report
from app.services.order_builder import order_request_from_decision, strategy_bucket_from_decision


class FakeDatabaseClient:
    def __init__(self):
        self.payloads = []

    async def create_risk_approval(self, payload, correlation_id):
        self.payloads.append({"payload": payload, "correlation_id": correlation_id})
        return {"status": "success"}


def execution_ready_decision(**overrides):
    decision = {
        "symbol": "ACGL",
        "action": "buy",
        "position_size": 10,
        "entry_price": 100,
        "risk_approval_id": "risk-1",
        "guard_plan": {
            "symbol": "ACGL",
            "side": "sell",
            "quantity": 10,
            "trigger_price": 95,
            "take_profit_price": 110,
        },
    }
    decision.update(overrides)
    return decision


def test_strategy_bucket_from_decision_prefers_stock_risk_context():
    decision = {
        "symbol": "ADBE",
        "strategy_bucket": "value_rebound",
        "stock_risk_context": {"strategy_bucket": "core_dividend"},
    }

    assert strategy_bucket_from_decision(decision) == "core_dividend"


def test_order_request_preserves_top_level_strategy_bucket():
    decision = execution_ready_decision(strategy_bucket="value_rebound")

    order = order_request_from_decision(decision, account_id=1, client_order_id_factory=lambda: "client-1")

    assert order.symbol == "ACGL"
    assert order.strategy_bucket == "value_rebound"


def test_order_request_preserves_portfolio_context_strategy_bucket():
    decision = execution_ready_decision(
        symbol="ADBE",
        position_size=5,
        entry_price=200,
        risk_approval_id="risk-2",
        guard_plan={
            "symbol": "ADBE",
            "side": "sell",
            "quantity": 5,
            "trigger_price": 190,
            "take_profit_price": 220,
        },
        portfolio_context={"strategy_bucket": "core_dividend"},
    )

    order = order_request_from_decision(decision, account_id=1, client_order_id_factory=lambda: "client-2")

    assert order.strategy_bucket == "core_dividend"


@pytest.mark.asyncio
async def test_risk_approval_metadata_preserves_strategy_bucket():
    db_client = FakeDatabaseClient()
    decision = {
        "approved": True,
        "symbol": "ADBE",
        "action": "buy",
        "position_size": 12,
        "strategy_bucket": "core_dividend",
    }

    approval_id = await persist_risk_approval(
        db_client=db_client,
        trade_decision=decision,
        account_id=1,
        correlation_id="corr-1",
    )

    assert approval_id.startswith("risk-corr-1-ADBE-")
    assert decision["strategy_bucket"] == "core_dividend"
    assert db_client.payloads[0]["payload"]["metadata"]["strategy_bucket"] == "core_dividend"


def test_audit_report_preserves_strategy_bucket_from_analysis_when_decision_missing():
    audit = dry_run_report(
        correlation_id="corr-2",
        flow="discover_analyze_trade_portfolio",
        symbol="ACGL",
        analysis_result={
            "ticker": "ACGL",
            "final_verdict": "buy",
            "strategy_bucket": "value_rebound",
        },
        trade_decision={"approved": False, "symbol": "ACGL", "reason": "already protected"},
        execution_result={"status": "not_attempted"},
        context_value=Decimal("0"),
        dry_run=False,
    )

    assert audit["strategy_bucket"] == "value_rebound"

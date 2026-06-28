from types import SimpleNamespace

import pytest

from app.services.trade_plan_lifecycle_service import (
    persist_trade_plan_created,
    persist_trade_plan_status,
    trade_plan_create_payload,
    trade_plan_status_payload,
)


def trade_plan_snapshot(**overrides):
    payload = {
        "plan_id": "plan-1",
        "correlation_id": "corr-1",
        "source": "single_analysis",
        "status": "risk_approved",
        "account_id": "1",
        "symbol": "aapl",
        "side": "buy",
        "order_type": "market",
        "entry_price": 100.0,
        "quantity": 5,
        "final_quantity": 5,
        "time_in_force": "GTC",
        "strategy": "trend_pullback",
        "strategy_bucket": "value_rebound",
        "final_verdict": "buy",
        "confidence_score": 0.7,
        "risk": {
            "max_loss_amount": 25,
            "max_loss_pct": 0.0025,
        },
        "exit": {
            "stop_loss": 95,
            "take_profit": 110,
        },
        "risk_approval_id": "risk-1",
        "manual_approval_required": False,
        "dry_run": False,
        "reasons": [],
        "guard_plan": {"stop_loss": 95},
        "metadata": {"approved": True},
    }
    payload.update(overrides)
    return payload


class FakeDbClient:
    def __init__(self, fail=False):
        self.fail = fail
        self.posts = []

    async def _post(self, endpoint, correlation_id, json_data=None):
        self.posts.append((endpoint, correlation_id, json_data))
        if self.fail:
            raise RuntimeError("database unavailable")
        return {"status": "success", "data": json_data or {}}

    def validate_standard_response(self, response):
        return SimpleNamespace(data=response.get("data"))


def test_trade_plan_create_payload_maps_manager_plan_to_database_shape():
    payload = trade_plan_create_payload(trade_plan_snapshot())

    assert payload["trade_plan_id"] == "plan-1"
    assert payload["account_id"] == "1"
    assert payload["symbol"] == "AAPL"
    assert payload["side"] == "buy"
    assert payload["status"] == "risk_approved"
    assert payload["risk_approval_id"] == "risk-1"
    assert payload["strategy_bucket"] == "value_rebound"
    assert payload["plan"]["plan_id"] == "plan-1"
    assert payload["metadata"]["manager_trade_plan_status"] == "risk_approved"


def test_trade_plan_status_payload_links_execution_identifiers():
    payload = trade_plan_status_payload(
        status="execution_submitted",
        reason="submitted",
        trade_decision={"risk_approval_id": "risk-1"},
        execution_result={
            "status": "submitted",
            "order": {"order_id": 123, "broker_order_id": "broker-1"},
            "execution_job": {"job_id": "job-1"},
        },
    )

    assert payload["status"] == "execution_submitted"
    assert payload["reason"] == "submitted"
    assert payload["risk_approval_id"] == "risk-1"
    assert payload["order_id"] == 123
    assert payload["execution_job_id"] == "job-1"
    assert payload["broker_order_id"] == "broker-1"
    assert payload["metadata"]["execution_result"]["status"] == "submitted"


@pytest.mark.asyncio
async def test_persist_trade_plan_created_posts_to_database():
    db_client = FakeDbClient()
    decision = {"trade_plan": trade_plan_snapshot()}

    result = await persist_trade_plan_created(
        db_client=db_client,
        trade_decision=decision,
        correlation_id="corr-1",
    )

    assert result["trade_plan_id"] == "plan-1"
    assert db_client.posts[0][0] == "/trade-plans"
    assert db_client.posts[0][1] == "corr-1"
    assert db_client.posts[0][2]["status"] == "risk_approved"
    assert decision["trade_plan_persisted"] is True


@pytest.mark.asyncio
async def test_persist_trade_plan_status_posts_to_database():
    db_client = FakeDbClient()
    decision = {"trade_plan": trade_plan_snapshot(), "risk_approval_id": "risk-1"}

    result = await persist_trade_plan_status(
        db_client=db_client,
        trade_decision=decision,
        correlation_id="corr-1",
        status="execution_submitted",
        reason="submitted",
        execution_result={"status": "submitted", "order": {"order_id": 123}},
    )

    assert result["status"] == "execution_submitted"
    assert db_client.posts[0][0] == "/trade-plans/plan-1/status"
    assert db_client.posts[0][2]["order_id"] == 123
    assert decision["trade_plan_last_persisted_status"] == "execution_submitted"


@pytest.mark.asyncio
async def test_persist_trade_plan_created_is_best_effort():
    db_client = FakeDbClient(fail=True)
    decision = {"trade_plan": trade_plan_snapshot()}

    result = await persist_trade_plan_created(
        db_client=db_client,
        trade_decision=decision,
        correlation_id="corr-1",
    )

    assert result is None
    assert "database unavailable" in decision["trade_plan_persist_error"]

from types import SimpleNamespace

import pytest

from app import config
from app.workflows.execution_workflow import (
    ensure_risk_approval_id,
    execute_portfolio_batch,
    execute_trade,
)


class FakeCreateOrderResponse:
    def __init__(self, *, order_id="order-1", status="PENDING"):
        self.order_id = order_id
        self.status = status

    def model_dump(self):
        return {"order_id": self.order_id, "status": self.status}


class FakeExecutionClient:
    def __init__(self, *, create_status="PENDING", validation_approved=True, batch_created=None):
        self.create_status = create_status
        self.validation_approved = validation_approved
        self.batch_created = batch_created if batch_created is not None else [{"order_id": "order-1"}]
        self.created_orders = []
        self.validated_batches = []
        self.executed_batches = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def create_order(self, order_request, correlation_id):
        self.created_orders.append((order_request, correlation_id))
        return FakeCreateOrderResponse(status=self.create_status)

    async def validate_order_batch(self, order_requests, correlation_id):
        self.validated_batches.append((order_requests, correlation_id))
        return {"status": "success", "data": {"approved": self.validation_approved}}

    async def execute_order_batch(self, order_requests, correlation_id):
        self.executed_batches.append((order_requests, correlation_id))
        return {"status": "success", "data": {"created": self.batch_created, "failed": []}}


class FakeDbClient:
    async def create_risk_approval(self, *args, **kwargs):
        return SimpleNamespace(approval_id="risk-db-1")


@pytest.fixture(autouse=True)
def force_paper_mode(monkeypatch):
    monkeypatch.setattr(config, "TRADING_MODE", "PAPER")


def test_ensure_risk_approval_id_prefers_risk_agent_response():
    decision = {"symbol": "AAPL", "risk_agent_response": {"data": {"approval_id": "risk-api-1"}}}

    assert ensure_risk_approval_id(decision, "cid") == "risk-api-1"
    assert decision["risk_approval_id"] == "risk-api-1"


def test_ensure_risk_approval_id_falls_back_to_correlation_symbol():
    decision = {"symbol": "AAPL"}

    assert ensure_risk_approval_id(decision, "cid") == "risk-cid-AAPL"
    assert decision["risk_approval_id"] == "risk-cid-AAPL"


@pytest.mark.asyncio
async def test_execute_trade_submits_order_in_paper_without_db_client():
    exec_client = FakeExecutionClient(create_status="PENDING")
    decision = {
        "symbol": "AAPL",
        "action": "buy",
        "position_size": 2,
        "entry_price": 100,
        "guard_plan": {"source": "risk"},
    }

    result = await execute_trade(exec_client, decision, account_id=1, correlation_id="cid")

    assert result["status"] == "submitted"
    assert result["risk_approval_id"] == "risk-cid-AAPL"
    assert len(exec_client.created_orders) == 1
    order_request, correlation_id = exec_client.created_orders[0]
    assert order_request.symbol == "AAPL"
    assert order_request.quantity == 2
    assert correlation_id == "cid"


@pytest.mark.asyncio
async def test_execute_trade_fails_closed_in_live_without_db_client(monkeypatch):
    monkeypatch.setattr(config, "TRADING_MODE", "LIVE")
    exec_client = FakeExecutionClient(create_status="PENDING")
    decision = {
        "symbol": "AAPL",
        "action": "buy",
        "position_size": 2,
        "entry_price": 100,
    }

    result = await execute_trade(exec_client, decision, account_id=1, correlation_id="cid")

    assert result["status"] == "failed"
    assert "Database client is required" in result["reason"]
    assert exec_client.created_orders == []


@pytest.mark.asyncio
async def test_execute_trade_rejects_non_pending_execution_status():
    exec_client = FakeExecutionClient(create_status="FAILED")
    decision = {
        "symbol": "AAPL",
        "action": "buy",
        "position_size": 2,
        "entry_price": 100,
    }

    result = await execute_trade(exec_client, decision, account_id=1, correlation_id="cid")

    assert result["status"] == "rejected"
    assert result["reason"] == "Execution Agent returned status: FAILED"


@pytest.mark.asyncio
async def test_execute_portfolio_batch_validates_and_executes_orders(monkeypatch):
    exec_client = FakeExecutionClient(validation_approved=True, batch_created=[{"order_id": "order-1"}])

    async def fake_persist_risk_approval(**kwargs):
        return f"risk-{kwargs['trade_decision']['symbol']}"

    monkeypatch.setattr(
        "app.workflows.execution_workflow.persist_risk_approval",
        fake_persist_risk_approval,
    )

    decisions = [
        {"symbol": "AAPL", "action": "buy", "position_size": 1, "entry_price": 100},
        {"symbol": "MSFT", "action": "sell", "position_size": 2, "entry_price": 200},
    ]

    result = await execute_portfolio_batch(
        exec_client=exec_client,
        decisions=decisions,
        account_id=1,
        correlation_id="cid",
        db_client=FakeDbClient(),
    )

    assert result["status"] == "submitted"
    assert result["validation"] == {"approved": True}
    assert result["created"] == [{"order_id": "order-1"}]
    assert result["failed_to_build"] == []
    assert len(exec_client.validated_batches[0][0]) == 2
    assert len(exec_client.executed_batches[0][0]) == 2


@pytest.mark.asyncio
async def test_execute_portfolio_batch_rejects_when_validation_rejects(monkeypatch):
    exec_client = FakeExecutionClient(validation_approved=False)

    async def fake_persist_risk_approval(**kwargs):
        return "risk-1"

    monkeypatch.setattr(
        "app.workflows.execution_workflow.persist_risk_approval",
        fake_persist_risk_approval,
    )

    result = await execute_portfolio_batch(
        exec_client=exec_client,
        decisions=[{"symbol": "AAPL", "action": "buy", "position_size": 1, "entry_price": 100}],
        account_id=1,
        correlation_id="cid",
        db_client=FakeDbClient(),
    )

    assert result["status"] == "rejected"
    assert result["created"] == []
    assert exec_client.executed_batches == []


@pytest.mark.asyncio
async def test_execute_portfolio_batch_skips_zero_position_size(monkeypatch):
    exec_client = FakeExecutionClient(validation_approved=True)

    async def fake_persist_risk_approval(**kwargs):
        return "risk-1"

    monkeypatch.setattr(
        "app.workflows.execution_workflow.persist_risk_approval",
        fake_persist_risk_approval,
    )

    result = await execute_portfolio_batch(
        exec_client=exec_client,
        decisions=[{"symbol": "AAPL", "action": "buy", "position_size": 0, "entry_price": 100}],
        account_id=1,
        correlation_id="cid",
        db_client=FakeDbClient(),
    )

    assert result["status"] == "not_attempted"
    assert result["failed"] == [
        {"symbol": "AAPL", "reason": "approved decision has zero position_size"}
    ]
    assert exec_client.validated_batches == []

import pytest

from app.contracts import CreateOrderResponse
from app.workflows.execution_workflow import execute_portfolio_batch, execute_trade


class FakeDatabaseClient:
    def __init__(self):
        self.approvals = []

    async def create_risk_approval(self, payload, correlation_id):
        self.approvals.append({"payload": payload, "correlation_id": correlation_id})
        return {"status": "success", "data": payload}


class FakeExecutionClient:
    def __init__(self):
        self.created_orders = []
        self.validated_batches = []
        self.executed_batches = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def create_order(self, order_request, correlation_id):
        self.created_orders.append({"order_request": order_request, "correlation_id": correlation_id})
        return CreateOrderResponse(
            order_id="order-1",
            client_order_id=order_request.client_order_id,
            status="pending",
        )

    async def validate_order_batch(self, order_requests, correlation_id):
        self.validated_batches.append({"order_requests": order_requests, "correlation_id": correlation_id})
        return {"status": "success", "data": {"approved": True, "errors": []}}

    async def execute_order_batch(self, order_requests, correlation_id):
        self.executed_batches.append({"order_requests": order_requests, "correlation_id": correlation_id})
        return {
            "status": "success",
            "data": {
                "created": [
                    {
                        "symbol": order.symbol,
                        "risk_approval_id": order.risk_approval_id,
                        "quantity": order.quantity,
                        "final_quantity": order.final_quantity,
                    }
                    for order in order_requests
                ],
                "failed": [],
            },
        }


def approved_decision(**overrides):
    decision = {
        "approved": True,
        "symbol": "AAPL",
        "action": "buy",
        "position_size": 10,
        "entry_price": 100.0,
        "stop_loss": 95.0,
        "take_profit": 110.0,
        "risk_amount": 50.0,
        "risk_agent_response": {"data": {"approval_id": "risk-approved-1"}},
        "guard_plan": {
            "source": "risk_agent",
            "trigger_price": 95.0,
            "take_profit_price": 110.0,
            "max_loss_amount": 50.0,
        },
        "stock_risk_context": {"strategy_bucket": "core_dividend"},
        "session_risk_context": {"trades_today": 1},
    }
    decision.update(overrides)
    return decision


@pytest.mark.asyncio
async def test_execute_trade_persists_approval_before_sending_execution_order():
    db_client = FakeDatabaseClient()
    exec_client = FakeExecutionClient()
    decision = approved_decision()

    result = await execute_trade(
        exec_client=exec_client,
        trade_decision=decision,
        account_id=1,
        correlation_id="corr-risk-contract",
        db_client=db_client,
    )

    assert result["status"] == "submitted"
    assert db_client.approvals[0]["payload"]["approval_id"] == "risk-approved-1"
    assert db_client.approvals[0]["payload"]["approved_quantity"] == 10
    assert db_client.approvals[0]["payload"]["metadata"]["guard_plan"] == decision["guard_plan"]

    order = exec_client.created_orders[0]["order_request"]
    assert order.risk_approval_id == "risk-approved-1"
    assert order.quantity == 10
    assert order.final_quantity == 10
    assert order.guard_plan == decision["guard_plan"]
    assert order.guard_plan["trigger_price"] == 95.0
    assert order.guard_plan["take_profit_price"] == 110.0
    assert order.strategy_bucket == "core_dividend"


@pytest.mark.asyncio
async def test_execute_trade_rejects_missing_database_client_in_live(monkeypatch):
    monkeypatch.setattr("app.workflows.execution_workflow.config.TRADING_MODE", "LIVE")
    exec_client = FakeExecutionClient()

    result = await execute_trade(
        exec_client=exec_client,
        trade_decision=approved_decision(),
        account_id=1,
        correlation_id="corr-live-no-db",
        db_client=None,
    )

    assert result["status"] == "failed"
    assert "Database client is required" in result["reason"]
    assert exec_client.created_orders == []


@pytest.mark.asyncio
async def test_execute_trade_rejects_decision_missing_take_profit_before_execution():
    db_client = FakeDatabaseClient()
    exec_client = FakeExecutionClient()
    decision = approved_decision(guard_plan={"source": "risk_agent", "trigger_price": 95.0})

    result = await execute_trade(
        exec_client=exec_client,
        trade_decision=decision,
        account_id=1,
        correlation_id="corr-no-tp",
        db_client=db_client,
    )

    assert result["status"] == "failed"
    assert "take_profit_price" in result["reason"]
    assert exec_client.created_orders == []


@pytest.mark.asyncio
async def test_execute_portfolio_batch_sends_only_risk_approved_order_contracts():
    db_client = FakeDatabaseClient()
    exec_client = FakeExecutionClient()
    decisions = [
        approved_decision(symbol="AAPL", risk_agent_response={"data": {"approval_id": "risk-aapl"}}),
        approved_decision(symbol="MSFT", risk_agent_response={"data": {"approval_id": "risk-msft"}}, position_size=5),
    ]

    result = await execute_portfolio_batch(
        exec_client=exec_client,
        decisions=decisions,
        account_id=1,
        correlation_id="corr-batch-risk-contract",
        db_client=db_client,
    )

    assert result["status"] == "submitted"
    assert [row["payload"]["approval_id"] for row in db_client.approvals] == ["risk-aapl", "risk-msft"]

    validated_orders = exec_client.validated_batches[0]["order_requests"]
    executed_orders = exec_client.executed_batches[0]["order_requests"]
    assert validated_orders == executed_orders
    assert [order.risk_approval_id for order in executed_orders] == ["risk-aapl", "risk-msft"]
    assert [order.final_quantity for order in executed_orders] == [10, 5]
    assert all(order.guard_plan for order in executed_orders)
    assert all(order.guard_plan["trigger_price"] for order in executed_orders)
    assert all(order.guard_plan["take_profit_price"] for order in executed_orders)

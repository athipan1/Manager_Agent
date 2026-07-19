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
    def __init__(
        self,
        *,
        create_status="PENDING",
        validation_approved=True,
        batch_created=None,
        validation_sequence=None,
    ):
        self.create_status = create_status
        self.validation_approved = validation_approved
        self.validation_sequence = list(validation_sequence or [])
        self.batch_created = (
            batch_created if batch_created is not None else [{"order_id": "order-1"}]
        )
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
        if self.validation_sequence:
            return {"status": "success", "data": self.validation_sequence.pop(0)}
        return {"status": "success", "data": {"approved": self.validation_approved}}

    async def execute_order_batch(self, order_requests, correlation_id):
        self.executed_batches.append((order_requests, correlation_id))
        return {
            "status": "success",
            "data": {"created": self.batch_created, "failed": []},
        }


class FakeDbClient:
    async def create_risk_approval(self, *args, **kwargs):
        return SimpleNamespace(approval_id="risk-db-1")


@pytest.fixture(autouse=True)
def force_paper_mode(monkeypatch):
    monkeypatch.setattr(config, "TRADING_MODE", "PAPER")


def execution_ready_decision(
    *,
    symbol="AAPL",
    action="buy",
    position_size=2,
    entry_price=100,
    risk_approval_id=None,
    strategy_bucket="core_dividend",
    **overrides,
):
    exit_side = "sell" if action in {"buy", "strong_buy"} else "buy"
    stop_price = entry_price * 0.95 if exit_side == "sell" else entry_price * 1.05
    take_profit_price = (
        entry_price * 1.10 if exit_side == "sell" else entry_price * 0.90
    )
    decision = {
        "symbol": symbol,
        "action": action,
        "position_size": position_size,
        "entry_price": entry_price,
        "strategy_bucket": strategy_bucket,
        "guard_plan": {
            "source": "risk",
            "symbol": symbol,
            "side": exit_side,
            "quantity": position_size,
            "trigger_price": stop_price,
            "take_profit_price": take_profit_price,
        },
    }
    if risk_approval_id is not None:
        decision["risk_approval_id"] = risk_approval_id
    decision.update(overrides)
    return decision


def test_ensure_risk_approval_id_prefers_risk_agent_response():
    decision = {
        "symbol": "AAPL",
        "risk_agent_response": {"data": {"approval_id": "risk-api-1"}},
    }

    assert ensure_risk_approval_id(decision, "cid") == "risk-api-1"
    assert decision["risk_approval_id"] == "risk-api-1"


def test_ensure_risk_approval_id_falls_back_to_correlation_symbol():
    decision = {"symbol": "AAPL"}

    assert ensure_risk_approval_id(decision, "cid") == "risk-cid-AAPL"
    assert decision["risk_approval_id"] == "risk-cid-AAPL"


@pytest.mark.asyncio
async def test_execute_trade_submits_order_in_paper_without_db_client():
    exec_client = FakeExecutionClient(create_status="PENDING")
    decision = execution_ready_decision()

    result = await execute_trade(
        exec_client, decision, account_id=1, correlation_id="cid"
    )

    assert result["status"] == "submitted"
    assert result["risk_approval_id"] == "risk-cid-AAPL"
    assert len(exec_client.created_orders) == 1
    order_request, correlation_id = exec_client.created_orders[0]
    assert order_request.symbol == "AAPL"
    assert order_request.quantity == 2
    assert order_request.strategy_bucket == "core_dividend"
    assert order_request.guard_plan["trigger_price"] == 95.0
    assert order_request.guard_plan["take_profit_price"] == 110.00000000000001
    assert correlation_id == "cid"


@pytest.mark.asyncio
async def test_execute_trade_fails_closed_in_live_without_db_client(monkeypatch):
    monkeypatch.setattr(config, "TRADING_MODE", "LIVE")
    exec_client = FakeExecutionClient(create_status="PENDING")
    decision = execution_ready_decision()

    result = await execute_trade(
        exec_client, decision, account_id=1, correlation_id="cid"
    )

    assert result["status"] == "failed"
    assert "Database client is required" in result["reason"]
    assert exec_client.created_orders == []


@pytest.mark.asyncio
async def test_execute_trade_rejects_non_pending_execution_status():
    exec_client = FakeExecutionClient(create_status="FAILED")
    decision = execution_ready_decision()

    result = await execute_trade(
        exec_client, decision, account_id=1, correlation_id="cid"
    )

    assert result["status"] == "rejected"
    assert result["reason"] == "Execution Agent returned status: FAILED"


@pytest.mark.asyncio
async def test_execute_portfolio_batch_validates_and_executes_orders(monkeypatch):
    exec_client = FakeExecutionClient(
        validation_approved=True,
        batch_created=[{"order_id": "order-1"}],
    )

    async def fake_persist_risk_approval(**kwargs):
        return f"risk-{kwargs['trade_decision']['symbol']}"

    monkeypatch.setattr(
        "app.workflows.execution_workflow.persist_risk_approval",
        fake_persist_risk_approval,
    )

    decisions = [
        execution_ready_decision(
            symbol="AAPL",
            action="buy",
            position_size=1,
            entry_price=100,
            strategy_bucket="core_dividend",
        ),
        execution_ready_decision(
            symbol="MSFT",
            action="sell",
            position_size=2,
            entry_price=200,
            strategy_bucket="unassigned",
        ),
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
async def test_execute_portfolio_batch_retries_after_open_order_conflict(monkeypatch):
    exec_client = FakeExecutionClient(
        validation_sequence=[
            {
                "approved": False,
                "errors": [
                    {
                        "code": "SYMBOL_ALREADY_HAS_OPEN_ORDER",
                        "symbols": ["ADBE"],
                        "message": "One or more symbols already have open orders.",
                    }
                ],
            },
            {"approved": True, "summary": {"symbols": ["ACGL"]}},
        ],
        batch_created=[{"symbol": "ACGL", "order_id": "order-acgl"}],
    )

    async def fake_persist_risk_approval(**kwargs):
        return f"risk-{kwargs['trade_decision']['symbol']}"

    monkeypatch.setattr(
        "app.workflows.execution_workflow.persist_risk_approval",
        fake_persist_risk_approval,
    )

    decisions = [
        execution_ready_decision(
            symbol="ADBE",
            action="buy",
            position_size=5,
            entry_price=196,
            quantity=5,
            final_quantity=5,
            strategy_bucket="core_dividend",
        ),
        execution_ready_decision(
            symbol="ACGL",
            action="buy",
            position_size=10,
            entry_price=90,
            quantity=10,
            final_quantity=10,
            strategy_bucket="value_rebound",
        ),
    ]

    result = await execute_portfolio_batch(
        exec_client=exec_client,
        decisions=decisions,
        account_id=1,
        correlation_id="cid",
        db_client=FakeDbClient(),
    )

    assert result["status"] == "submitted"
    assert len(exec_client.validated_batches) == 2
    assert [order.symbol for order in exec_client.validated_batches[0][0]] == [
        "ADBE",
        "ACGL",
    ]
    assert [order.symbol for order in exec_client.validated_batches[1][0]] == [
        "ACGL"
    ]
    assert [order.symbol for order in exec_client.executed_batches[0][0]] == [
        "ACGL"
    ]
    assert result["skipped_open_order_conflicts"] == [
        {
            "symbol": "ADBE",
            "reason": "symbol already has an open broker order",
            "risk_approval_id": "risk-ADBE",
            "quantity": 5,
            "final_quantity": 5,
        }
    ]
    assert (
        result["validation"]["initial_validation"]["errors"][0]["code"]
        == "SYMBOL_ALREADY_HAS_OPEN_ORDER"
    )


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
        decisions=[
            execution_ready_decision(
                symbol="AAPL",
                action="buy",
                position_size=1,
                entry_price=100,
            )
        ],
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
        decisions=[
            execution_ready_decision(
                symbol="AAPL",
                action="buy",
                position_size=0,
                entry_price=100,
            )
        ],
        account_id=1,
        correlation_id="cid",
        db_client=FakeDbClient(),
    )

    assert result["status"] == "not_attempted"
    assert result["failed"] == [
        {
            "symbol": "AAPL",
            "reason": "approved decision has zero executable quantity",
            "position_size": 0,
            "final_quantity": None,
            "quantity": None,
        }
    ]
    assert exec_client.validated_batches == []


@pytest.mark.asyncio
async def test_hourly_retry_reuses_deterministic_order_and_does_not_submit(monkeypatch):
    class ExistingOrderDb(FakeDbClient):
        async def get_order_by_trade_id(self, trade_id, correlation_id):
            return {"trade_id": trade_id, "status": "placed"}

    async def unexpected_persist(**kwargs):
        raise AssertionError("risk approval must not be recreated for duplicate cycle")

    monkeypatch.setattr(
        "app.workflows.execution_workflow.persist_risk_approval",
        unexpected_persist,
    )
    exec_client = FakeExecutionClient()
    result = await execute_portfolio_batch(
        exec_client=exec_client,
        decisions=[execution_ready_decision(symbol="AAPL")],
        account_id=1,
        correlation_id="hourly-paper-account-20260719T12-123",
        db_client=ExistingOrderDb(),
    )
    assert result["status"] == "not_attempted"
    assert result["duplicate_orders"][0]["symbol"] == "AAPL"
    assert exec_client.validated_batches == []
    assert exec_client.executed_batches == []


@pytest.mark.asyncio
async def test_hourly_automatic_sell_is_blocked_before_execution(monkeypatch):
    class EmptyOrderDb(FakeDbClient):
        async def get_order_by_trade_id(self, trade_id, correlation_id):
            return None

    exec_client = FakeExecutionClient()
    result = await execute_portfolio_batch(
        exec_client=exec_client,
        decisions=[
            execution_ready_decision(
                symbol="AAPL",
                action="sell",
                strategy_bucket="unassigned",
            )
        ],
        account_id=1,
        correlation_id="hourly-paper-account-20260719T12-123",
        db_client=EmptyOrderDb(),
    )
    assert result["status"] == "not_attempted"
    assert "automatic PARTIAL_EXIT and EXIT_ALL are blocked" in result["failed"][0]["reason"]
    assert exec_client.executed_batches == []

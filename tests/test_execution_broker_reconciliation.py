import pytest

from app import config
from app.contracts import CreateOrderRequest
from app.execution_client import ExecutionAgentClient


class FakeExecutionClient(ExecutionAgentClient):
    def __init__(self, *, reconcile_payload=None):
        self.calls = []
        self.reconcile_payload = reconcile_payload or {"status": "success", "data": {"ok": True, "database_sync": {"status": "success"}}}

    async def _post(self, url, correlation_id, json_data=None, extra_headers=None):
        self.calls.append({"url": url, "json_data": json_data, "extra_headers": extra_headers})
        if url.startswith("/broker/reconcile"):
            return self.reconcile_payload
        if url == "/execute":
            return {
                "status": "success",
                "data": {
                    "order_id": "order-1",
                    "trade_id": "client-1",
                    "status": "placed",
                    "reason": None,
                },
            }
        raise AssertionError(f"Unexpected URL {url}")


def order_request():
    return CreateOrderRequest(
        client_order_id="client-1",
        account_id="1",
        symbol="AAPL",
        side="buy",
        order_type="market",
        quantity=1,
        price=100.0,
        risk_approval_id="risk-1",
        final_quantity=1,
    )


@pytest.mark.asyncio
async def test_create_order_reconciles_before_execute(monkeypatch):
    monkeypatch.setattr(config, "BROKER_RECONCILE_BEFORE_EXECUTION", True)
    monkeypatch.setattr(config, "BROKER_RECONCILE_PUSH_TO_DATABASE", True)
    monkeypatch.setattr(config, "BROKER_RECONCILE_REQUIRED", False)
    client = FakeExecutionClient()

    response = await client.create_order(order_request(), "corr-1")

    assert response.status == "placed"
    assert client.calls[0]["url"] == "/broker/reconcile?account_id=1&push_to_database=true"
    assert client.calls[1]["url"] == "/execute"


@pytest.mark.asyncio
async def test_create_order_blocks_execute_when_required_reconciliation_fails(monkeypatch):
    monkeypatch.setattr(config, "BROKER_RECONCILE_BEFORE_EXECUTION", True)
    monkeypatch.setattr(config, "BROKER_RECONCILE_PUSH_TO_DATABASE", True)
    monkeypatch.setattr(config, "BROKER_RECONCILE_REQUIRED", True)
    client = FakeExecutionClient(reconcile_payload={"status": "success", "data": {"ok": False, "database_sync": {"status": "failed"}}})

    response = await client.create_order(order_request(), "corr-1")

    assert response.status == "failed"
    assert response.order_id == "broker-reconciliation"
    assert [call["url"] for call in client.calls] == ["/broker/reconcile?account_id=1&push_to_database=true"]


@pytest.mark.asyncio
async def test_create_order_can_skip_reconciliation(monkeypatch):
    monkeypatch.setattr(config, "BROKER_RECONCILE_BEFORE_EXECUTION", False)
    monkeypatch.setattr(config, "BROKER_RECONCILE_REQUIRED", False)
    client = FakeExecutionClient()

    response = await client.create_order(order_request(), "corr-1")

    assert response.status == "placed"
    assert [call["url"] for call in client.calls] == ["/execute"]

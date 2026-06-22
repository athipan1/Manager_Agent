import pytest

from app import config
from app.database_client import DatabaseAgentClient


def standard(data):
    return {
        "status": "success",
        "agent_type": "database",
        "version": "1.0.0",
        "timestamp": "2026-06-22T00:00:00Z",
        "data": data,
    }


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def model_dump(self, mode="json"):
        return standard(self.data)


class FakeDatabaseClient(DatabaseAgentClient):
    def __init__(self):
        self.calls = []
        self.base_url = "fake-database"
        self._broker_context_reconciled_accounts = set()
        self._broker_context_by_account = {}

    async def _get(self, url, correlation_id, **kwargs):
        self.calls.append({"method": "GET", "url": url})
        if url.endswith("/balance"):
            return standard({"cash_balance": "102037.87"})
        if url.endswith("/positions"):
            return standard([
                {"symbol": "AAPL", "quantity": 1, "average_cost": "254.48", "current_market_price": "299.44"},
                {"symbol": "ACGL", "quantity": 2190, "average_cost": "91.31", "current_market_price": "92.22"},
            ])
        if url.endswith("/orders"):
            return standard([])
        if "/risk/session" in url:
            return standard({"account_id": "1", "symbol": "ACGL", "daily_realized_pnl": 0.0})
        raise AssertionError(f"Unexpected GET {url}")


class FakeExecutionClient:
    calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def reconcile_broker_state(self, account_id, correlation_id, *, push_to_database=True):
        self.__class__.calls.append({
            "account_id": str(account_id),
            "correlation_id": correlation_id,
            "push_to_database": push_to_database,
        })
        return FakeResponse({"ok": True, "database_sync": {"status": "success"}})


@pytest.mark.asyncio
async def test_get_account_balance_reconciles_broker_once(monkeypatch):
    monkeypatch.setattr(config, "BROKER_RECONCILE_BEFORE_CONTEXT", True)
    monkeypatch.setattr(config, "BROKER_RECONCILE_PUSH_TO_DATABASE", True)
    monkeypatch.setattr(config, "BROKER_RECONCILE_CONTEXT_REQUIRED", False)
    monkeypatch.setattr("app.execution_client.ExecutionAgentClient", FakeExecutionClient)
    FakeExecutionClient.calls = []
    client = FakeDatabaseClient()

    balance = await client.get_account_balance(1, "corr-1")
    positions = await client.get_positions(1, "corr-1")

    assert str(balance.cash_balance) == "102037.87"
    assert len(positions) == 2
    assert FakeExecutionClient.calls == [{"account_id": "1", "correlation_id": "corr-1", "push_to_database": True}]
    assert [call["url"] for call in client.calls] == ["/accounts/1/balance", "/accounts/1/positions"]


@pytest.mark.asyncio
async def test_database_context_reconciliation_can_be_disabled(monkeypatch):
    monkeypatch.setattr(config, "BROKER_RECONCILE_BEFORE_CONTEXT", False)
    monkeypatch.setattr("app.execution_client.ExecutionAgentClient", FakeExecutionClient)
    FakeExecutionClient.calls = []
    client = FakeDatabaseClient()

    await client.get_positions(1, "corr-1")

    assert FakeExecutionClient.calls == []
    assert [call["url"] for call in client.calls] == ["/accounts/1/positions"]

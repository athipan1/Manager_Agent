import pytest

from app.database_client import DatabaseAgentClient


def standard(data):
    return {
        "status": "success",
        "agent_type": "database",
        "version": "1.0.0",
        "timestamp": "2026-06-22T00:00:00Z",
        "data": data,
    }


class FakeExecutionClient:
    calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def reconcile_broker_state(self, account_id, correlation_id, *, push_to_database=True):
        self.__class__.calls.append({"account_id": str(account_id), "push_to_database": push_to_database})
        return type("Resp", (), {"data": {
            "ok": True,
            "broker_state": {
                "account": {"cash": "-100223.4", "equity": "102016.81", "buying_power": "3827.07"},
                "positions": [
                    {"symbol": "AAPL", "qty": "1", "avg_entry_price": "254.48", "current_price": "300.3", "market_value": "300.3"},
                    {"symbol": "ACGL", "qty": "2190", "avg_entry_price": "91.31", "current_price": "92.21", "market_value": "201939.9"},
                ],
                "open_orders": [],
            },
        }})()


class FakeDatabaseClient(DatabaseAgentClient):
    def __init__(self):
        self.calls = []
        self.base_url = "fake-database"
        self._broker_context_reconciled_accounts = set()
        self._broker_context_by_account = {}

    async def _get(self, url, correlation_id, **kwargs):
        self.calls.append(url)
        if url.endswith("/balance"):
            return standard({"cash_balance": "1000000.0"})
        if url.endswith("/positions"):
            return standard([])
        if url.endswith("/orders"):
            return standard([])
        raise AssertionError(f"Unexpected GET {url}")


@pytest.mark.asyncio
async def test_get_positions_returns_broker_positions_when_database_is_empty(monkeypatch):
    monkeypatch.setattr("app.execution_client.ExecutionAgentClient", FakeExecutionClient)
    FakeExecutionClient.calls = []
    client = FakeDatabaseClient()

    positions = await client.get_positions(1, "corr-1")

    assert len(positions) == 2
    acgl = next(p for p in positions if p.symbol == "ACGL")
    assert acgl.quantity == 2190
    assert str(acgl.average_cost) == "91.31"
    assert str(acgl.current_market_price) == "92.21"
    assert FakeExecutionClient.calls == [{"account_id": "1", "push_to_database": True}]


@pytest.mark.asyncio
async def test_get_account_balance_uses_broker_equity_when_database_cash_is_stale(monkeypatch):
    monkeypatch.setattr("app.execution_client.ExecutionAgentClient", FakeExecutionClient)
    FakeExecutionClient.calls = []
    client = FakeDatabaseClient()

    balance = await client.get_account_balance(1, "corr-1")

    assert str(balance.cash_balance) == "102016.81"
    assert FakeExecutionClient.calls == [{"account_id": "1", "push_to_database": True}]

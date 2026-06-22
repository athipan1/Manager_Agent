import pytest

from app.dashboard_routes import _dashboard_payload


class FakeDBClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get_account_balance(self, account_id, correlation_id):
        return {"account_id": account_id, "cash_balance": "1000000.0"}

    async def get_positions(self, account_id, correlation_id):
        return []

    async def get_orders(self, account_id, correlation_id):
        return []

    async def get_trade_history(self, account_id, correlation_id):
        return []


class FakeExecutionClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def reconcile_broker_state(self, account_id, correlation_id):
        return type("Resp", (), {"data": {
            "ok": True,
            "database_sync": {"status": "success"},
            "broker_state": {
                "account": {"cash": "-100223.4", "buying_power": "4554.22", "equity": "102379.75"},
                "positions": [
                    {"symbol": "AAPL", "qty": "1", "avg_entry_price": "254.48", "current_price": "301.905", "market_value": "301.905"},
                    {"symbol": "ACGL", "qty": "2190", "avg_entry_price": "91.31", "current_price": "92.375", "market_value": "202301.25"},
                ],
                "open_orders": [],
            },
        }})()

    async def broker_state(self, account_id, correlation_id):
        raise AssertionError("broker_state should not be called when reconcile returns broker_state")


@pytest.mark.asyncio
async def test_dashboard_uses_broker_fallback_when_database_context_is_stale(monkeypatch):
    monkeypatch.setattr("app.dashboard_routes.DatabaseAgentClient", FakeDBClient)
    monkeypatch.setattr("app.dashboard_routes.ExecutionAgentClient", FakeExecutionClient)

    payload = await _dashboard_payload("1", "corr-1")

    assert payload["data_source"] == "broker_fallback"
    assert payload["summary"]["position_count"] == 2
    assert payload["summary"]["open_order_count"] == 0
    assert payload["balance"]["cash_balance"] == "-100223.4"
    assert payload["positions"][1]["symbol"] == "ACGL"
    assert payload["problems"][0]["alert_type"] == "dashboard_broker_fallback"

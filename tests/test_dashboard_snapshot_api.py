import datetime
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.dashboard_routes import _load_broker_state
from app.main import app


def dashboard_payload(*, positions=None, orders=None, problems=None, balance=None):
    positions = [] if positions is None else positions
    orders = [] if orders is None else orders
    problems = [] if problems is None else problems
    return {
        "generated_at": "2026-07-21T10:00:00Z",
        "data_source": "database",
        "balance": balance or {
            "cash_balance": "10000.50",
            "equity": "12000.75",
            "buying_power": "20000",
        },
        "positions": positions,
        "open_orders": orders,
        "curator_signals": [],
        "problems": problems,
        "summary": {"problem_count": len(problems)},
        "broker_sync": {"api_key": "must-not-leak", "internal_order_id": "broker-1"},
        "database_sync": {"database_url": "postgresql://must-not-leak"},
    }


def request_snapshot(payload):
    loader = AsyncMock(return_value=payload)
    with patch("app.dashboard_routes._dashboard_payload", new=loader):
        response = TestClient(app).get("/dashboard/snapshot")
    loader.assert_awaited_once()
    assert loader.await_args.kwargs["reconcile_broker"] is False
    return response


def test_dashboard_snapshot_has_versioned_schema_and_timestamp(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("BROKER_MODE", "ALPACA")
    response = request_snapshot(dashboard_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["schemaVersion"] == "dashboard-snapshot.v1"
    assert body["mode"] == "PAPER"
    assert body["brokerMode"] == "ALPACA"
    assert body["flow"] == "portfolio_review"
    assert datetime.datetime.fromisoformat(body["generatedAt"].replace("Z", "+00:00")).tzinfo is not None
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert response.headers["x-content-type-options"] == "nosniff"


def test_dashboard_snapshot_supports_empty_portfolio():
    body = request_snapshot(dashboard_payload()).json()
    assert body["positions"] == []
    assert body["openOrders"] == []
    assert body["summary"]["positionCount"] == 0
    assert body["summary"]["openOrderCount"] == 0


def test_dashboard_snapshot_maps_active_positions_and_open_orders():
    payload = dashboard_payload(
        positions=[{
            "symbol": "aapl",
            "qty": "2",
            "avg_entry_price": "100",
            "current_price": "110",
            "market_value": "220",
            "unrealized_pl": "20",
            "strategy_bucket": "quality_growth",
            "broker_position_id": "must-not-leak",
        }],
        orders=[{
            "id": "must-not-leak",
            "broker_order_id": "must-not-leak",
            "symbol": "AAPL",
            "side": "sell",
            "qty": "2",
            "order_class": "bracket",
            "type": "limit",
            "status": "new",
            "limit_price": "125",
        }],
    )
    body = request_snapshot(payload).json()

    assert body["positions"][0] == {
        "symbol": "AAPL",
        "quantity": 2.0,
        "averageCost": 100.0,
        "currentPrice": 110.0,
        "marketValue": 220.0,
        "unrealizedPnL": 20.0,
        "bucket": "quality_growth",
        "protection": {
            "status": "bracket_protected",
            "hasStopLoss": True,
            "hasTakeProfit": True,
            "hasBracket": True,
        },
    }
    assert body["openOrders"][0]["symbol"] == "AAPL"
    assert body["summary"]["serviceStatus"] == "OK"


def test_dashboard_snapshot_reports_simulator_mode(monkeypatch):
    monkeypatch.setenv("TRADING_MODE", "PAPER")
    monkeypatch.setenv("BROKER_MODE", "SIMULATOR")
    body = request_snapshot(dashboard_payload()).json()
    assert body["mode"] == "PAPER"
    assert body["brokerMode"] == "SIMULATOR"
    assert body["account"]["mode"] == "PAPER"


def test_dashboard_snapshot_does_not_expose_sensitive_fields():
    payload = dashboard_payload(
        positions=[{"symbol": "AAPL", "api_key": "alpaca-key"}],
        orders=[{"symbol": "AAPL", "id": "order-id", "client_order_id": "client-id"}],
        balance={"cash": 10, "account_id": "broker-account", "secret": "hidden"},
    )
    serialized = json.dumps(request_snapshot(payload).json()).lower()
    for forbidden in (
        "api_key",
        "secret",
        "database_url",
        "postgresql://",
        "broker_order_id",
        "client_order_id",
        "broker-account",
        "order-id",
        "alpaca-key",
    ):
        assert forbidden not in serialized


def test_dashboard_snapshot_fails_safe_when_services_raise():
    with patch("app.dashboard_routes._dashboard_payload", new=AsyncMock(side_effect=RuntimeError("secret internal URL"))):
        response = TestClient(app).get("/dashboard/snapshot")

    assert response.status_code == 200
    body = response.json()
    assert body["positions"] == []
    assert body["openOrders"] == []
    assert body["summary"]["serviceStatus"] == "DEGRADED"
    assert "secret internal url" not in response.text.lower()


@pytest.mark.asyncio
async def test_public_snapshot_broker_read_does_not_reconcile_or_write(monkeypatch):
    class ReadOnlyExecutionClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def reconcile_broker_state(self, account_id, correlation_id):
            raise AssertionError("Read-only dashboard must not reconcile broker state")

        async def broker_state(self, account_id, correlation_id):
            return type("Response", (), {"data": {"account": {}, "positions": [], "open_orders": []}})()

    monkeypatch.setattr("app.dashboard_routes.ExecutionAgentClient", ReadOnlyExecutionClient)
    result = await _load_broker_state("1", "corr-read-only", reconcile=False)
    assert result["status"] == "success"
    assert result["mode"] == "state"

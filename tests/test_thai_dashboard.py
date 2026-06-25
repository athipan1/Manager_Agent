from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


def test_thai_dashboard_page_is_available():
    response = TestClient(app).get("/dashboard")
    assert response.status_code == 200
    assert "แดชบอร์ดระบบเทรด" in response.text
    assert "หุ้นที่ถืออยู่" in response.text
    assert "ประวัติการซื้อขาย" in response.text
    assert "Database Sync" in response.text


def test_dashboard_data_returns_thai_dashboard_payload():
    client = TestClient(app)
    with patch("app.dashboard_routes.DatabaseAgentClient") as db_client_cls:
        db_client = db_client_cls.return_value.__aenter__.return_value
        db_client.get_broker_sync_status = AsyncMock(return_value={
            "mismatch": {
                "is_synced": True,
                "summary": {"status": "synced", "severity": "ok", "recommended_action": "none"},
                "diagnostics": {},
            }
        })
        db_client.get_account_balance = AsyncMock(return_value={"cash_balance": 10000})
        db_client.get_positions = AsyncMock(return_value=[{"symbol": "AAPL", "quantity": 2}])
        db_client.get_orders = AsyncMock(return_value=[{"order_id": "o1", "symbol": "AAPL", "status": "pending", "quantity": 1}])
        db_client.get_trade_history = AsyncMock(return_value=[{"trade_id": "t1", "symbol": "AAPL", "side": "buy"}])

        response = client.get("/dashboard/data?account_id=1")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    data = body["data"]
    assert data["account_id"] == "1"
    assert data["summary"]["position_count"] == 1
    assert data["summary"]["open_order_count"] == 1
    assert data["summary"]["trade_count"] == 1
    assert data["summary"]["database_sync_status"] == "synced"
    assert data["database_sync"]["mismatch"]["summary"]["recommended_action"] == "none"


def test_dashboard_broker_fallback_includes_database_sync_diagnostics():
    client = TestClient(app)
    broker_state = {
        "account": {"cash": "9000", "equity": "10000"},
        "positions": [{"symbol": "AAPL", "qty": "2", "current_price": "100"}],
        "open_orders": [{"id": "broker-order-1", "symbol": "AAPL", "status": "new", "qty": "1"}],
    }
    database_sync = {
        "mismatch": {
            "is_synced": False,
            "summary": {"status": "mismatch", "severity": "warning", "recommended_action": "refresh_broker_sync"},
            "diagnostics": {
                "positions": {"missing_in_database": ["AAPL"]},
                "open_orders": {"missing_in_database": ["broker-order-1"]},
            },
        }
    }

    with patch("app.dashboard_routes._load_broker_state", new=AsyncMock(return_value={"status": "success", "payload": {"broker_state": broker_state}, "broker_state": broker_state})), \
         patch("app.dashboard_routes.DatabaseAgentClient") as db_client_cls:
        db_client = db_client_cls.return_value.__aenter__.return_value
        db_client.get_broker_sync_status = AsyncMock(return_value=database_sync)
        db_client.get_account_balance = AsyncMock(return_value={"cash_balance": 10000})
        db_client.get_positions = AsyncMock(return_value=[])
        db_client.get_orders = AsyncMock(return_value=[])
        db_client.get_trade_history = AsyncMock(return_value=[])

        response = client.get("/dashboard/data?account_id=1")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["data_source"] == "broker_fallback"
    assert data["summary"]["database_sync_status"] == "mismatch"
    assert data["positions"] == broker_state["positions"]
    assert data["open_orders"] == broker_state["open_orders"]
    fallback_alert = data["problems"][0]
    assert fallback_alert["alert_type"] == "dashboard_broker_fallback"
    assert fallback_alert["metadata"]["database_sync_summary"]["recommended_action"] == "refresh_broker_sync"
    assert fallback_alert["metadata"]["database_sync_diagnostics"]["open_orders"]["missing_in_database"] == ["broker-order-1"]

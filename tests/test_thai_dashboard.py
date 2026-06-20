from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


def test_thai_dashboard_page_is_available():
    response = TestClient(app).get("/dashboard")
    assert response.status_code == 200
    assert "แดชบอร์ดระบบเทรด" in response.text
    assert "หุ้นที่ถืออยู่" in response.text
    assert "ประวัติการซื้อขาย" in response.text


def test_dashboard_data_returns_thai_dashboard_payload():
    client = TestClient(app)
    with patch("app.dashboard_routes.DatabaseAgentClient") as db_client_cls:
        db_client = db_client_cls.return_value.__aenter__.return_value
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

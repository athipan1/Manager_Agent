from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
import pytest
import datetime

from app.main import app
from app.models import AccountBalance, CreateOrderResponse, Order

client = TestClient(app)

# --- Mock Data ---
# These represent the raw, legacy responses from the agents
SUCCESS_TECH_RESPONSE = {
    "status": "success", "agent_type": "technical", "ticker": "GOOGL",
    "data": {"current_price": 2800.0, "action": "buy", "confidence_score": 0.85, "indicators": {}}
}
SUCCESS_FUND_RESPONSE = {
    "status": "success", "agent_type": "fundamental", "ticker": "GOOGL",
    "data": {"action": "buy", "confidence_score": 0.9, "analysis_summary": "", "metrics": {}}
}
ERROR_RESPONSE = {"error": "Agent failed"}

@pytest.fixture(autouse=True)
def mock_db_client():
    """Fixture to mock the DatabaseAgentClient for all tests in this module."""
    with patch("app.main.DatabaseAgentClient") as mock:
        instance = mock.return_value.__aenter__.return_value
        instance.get_account_balance.return_value = AccountBalance(cash_balance=10000.0)
        instance.get_positions.return_value = []
        instance.create_order.return_value = CreateOrderResponse(order_id=123, status="pending")
        instance.execute_order.return_value = Order(
            order_id=123, account_id=1, symbol="GOOGL", order_type="BUY",
            quantity=1, price=2800.0, status="executed",
            timestamp=datetime.datetime.now(datetime.UTC).isoformat()
        )
        yield mock

# --- Test Cases ---

@patch('app.main.call_agents', new_callable=AsyncMock)
def test_analyze_ticker_both_agents_succeed(mock_call_agents):
    """Test when both agents return successful legacy responses that get normalized."""
    mock_call_agents.return_value = (SUCCESS_TECH_RESPONSE, SUCCESS_FUND_RESPONSE)

    response = client.post("/analyze", json={"ticker": "GOOGL"})

    assert response.status_code == 200
    data = response.json()
    assert data["ticker"] == "GOOGL"
    assert data["status"] == "complete"
    assert data["final_verdict"] is not None
    assert data["details"]["technical"]["action"] == "buy"
    assert data["details"]["fundamental"]["action"] == "buy"

@patch('app.main.call_agents', new_callable=AsyncMock)
def test_analyze_ticker_technical_agent_fails(mock_call_agents):
    """Test when the technical agent fails but the fundamental agent succeeds."""
    mock_call_agents.return_value = (ERROR_RESPONSE, SUCCESS_FUND_RESPONSE)

    response = client.post("/analyze", json={"ticker": "GOOGL"})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "partial"
    assert data["details"]["technical"] is None
    assert data["details"]["fundamental"] is not None
    assert data["details"]["fundamental"]["action"] == "buy"

@patch('app.main.call_agents', new_callable=AsyncMock)
def test_analyze_ticker_fundamental_agent_fails(mock_call_agents):
    """Test when the fundamental agent fails but the technical agent succeeds."""
    mock_call_agents.return_value = (SUCCESS_TECH_RESPONSE, ERROR_RESPONSE)

    response = client.post("/analyze", json={"ticker": "GOOGL"})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "partial"
    assert data["details"]["technical"] is not None
    assert data["details"]["fundamental"] is None
    assert data["details"]["technical"]["action"] == "buy"

@patch('app.main.call_agents', new_callable=AsyncMock)
def test_analyze_ticker_both_agents_fail(mock_call_agents):
    """Test when both agents provide responses that cannot be normalized."""
    mock_call_agents.return_value = (ERROR_RESPONSE, ERROR_RESPONSE)

    response = client.post("/analyze", json={"ticker": "GOOGL"})

    assert response.status_code == 500
    assert "Both Technical and Fundamental Agents failed" in response.json()["detail"]

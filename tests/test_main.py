from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
import pytest
import datetime
from decimal import Decimal

from app.main import app
from app.models import AccountBalance, CreateOrderResponse, Order

client = TestClient(app)

# --- Mock Data ---
# Updated to the new StandardAgentResponse format

TIMESTAMP = datetime.datetime.now(datetime.UTC).isoformat()

SUCCESS_TECH_RESPONSE = {
    "status": "success", "agent_type": "technical", "version": "2.0", "timestamp": TIMESTAMP,
    "data": { "action": "buy", "confidence_score": 0.85, "reason": "Bullish indicators." }
}
SUCCESS_FUND_RESPONSE = {
    "status": "success", "agent_type": "fundamental", "version": "1.0", "timestamp": TIMESTAMP,
    "data": { "action": "buy", "confidence_score": 0.9, "reason": "Strong fundamentals." }
}

# A valid, standard error response that the adapter should handle gracefully.
ERROR_RESPONSE_STANDARD = {
    "status": "error", "agent_type": "technical", "version": "2.0", "timestamp": TIMESTAMP,
    "error": {"code": 500, "message": "Agent failed to process"},
    # Data block is still required by the model schema.
    "data": {"action": "hold", "confidence_score": 0.0, "reason": "N/A"}
}

# A malformed response that will fail normalization and result in `None`.
UNNORMALIZABLE_RESPONSE = {"detail": "This response is invalid"}

@pytest.fixture(autouse=True)
def mock_db_client():
    """Fixture to mock the DatabaseAgentClient for all tests in this module."""
    with patch("app.main.DatabaseAgentClient") as mock:
        instance = mock.return_value.__aenter__.return_value
        instance.get_account_balance.return_value = AccountBalance(cash_balance=Decimal("10000.0"))
        instance.get_positions.return_value = []
        instance.create_order.return_value = CreateOrderResponse(order_id=123, status="pending")
        instance.execute_order.return_value = Order(
            order_id=123, account_id=1, symbol="GOOGL", order_type="BUY",
            quantity=1, price=Decimal("2800.0"), status="executed",
            timestamp=datetime.datetime.now(datetime.UTC).isoformat()
        )
        yield mock

# --- Test Cases ---

@patch('app.main.call_agents', new_callable=AsyncMock)
def test_analyze_both_agents_succeed(mock_call_agents):
    """Test the happy path where both agents return successful standard responses."""
    mock_call_agents.return_value = (SUCCESS_TECH_RESPONSE, SUCCESS_FUND_RESPONSE)
    response = client.post("/analyze", json={"ticker": "GOOGL"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "complete"
    assert data["details"]["technical"]["action"] == "buy"
    assert data["details"]["fundamental"]["action"] == "buy"

@patch('app.main.call_agents', new_callable=AsyncMock)
def test_analyze_one_agent_returns_standard_error(mock_call_agents):
    """Test graceful handling when one agent returns a standard, well-formed error."""
    # The adapter normalizes this error to a 'hold' action.
    mock_call_agents.return_value = (ERROR_RESPONSE_STANDARD, SUCCESS_FUND_RESPONSE)
    response = client.post("/analyze", json={"ticker": "GOOGL"})
    assert response.status_code == 200
    data = response.json()
    # Status is 'complete' because the error was handled and normalized.
    assert data["status"] == "complete"
    assert data["details"]["technical"]["action"] == "hold"
    assert data["details"]["fundamental"]["action"] == "buy"

@patch('app.main.call_agents', new_callable=AsyncMock)
def test_analyze_one_agent_returns_unnormalizable_data(mock_call_agents):
    """Test 'partial' status when one agent's response is malformed and cannot be normalized."""
    mock_call_agents.return_value = (SUCCESS_TECH_RESPONSE, UNNORMALIZABLE_RESPONSE)
    response = client.post("/analyze", json={"ticker": "GOOGL"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "partial"
    assert data["details"]["technical"] is not None
    assert data["details"]["fundamental"] is None # Normalization returned None
    assert data["details"]["technical"]["action"] == "buy"

@patch('app.main.call_agents', new_callable=AsyncMock)
def test_analyze_both_agents_return_unnormalizable_data(mock_call_agents):
    """Test 500 error when both agents provide malformed responses."""
    mock_call_agents.return_value = (UNNORMALIZABLE_RESPONSE, UNNORMALIZABLE_RESPONSE)
    response = client.post("/analyze", json={"ticker": "GOOGL"})
    assert response.status_code == 500
    assert "Both Technical and Fundamental Agents failed" in response.json()["detail"]

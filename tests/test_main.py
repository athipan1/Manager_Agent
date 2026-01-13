from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
import pytest
import datetime
from decimal import Decimal
import uuid

from app.main import app
from app.models import AccountBalance
from app.models import CreateOrderResponse as ExecutionCreateOrderResponse

client = TestClient(app)

# --- Mock Data ---

TIMESTAMP = datetime.datetime.now(datetime.UTC).isoformat()

SUCCESS_TECH_RESPONSE = {
    "status": "success", "agent_type": "technical", "version": "2.0", "timestamp": TIMESTAMP,
    "data": { "action": "buy", "confidence_score": 0.85, "reason": "Bullish indicators." }
}
SUCCESS_FUND_RESPONSE = {
    "status": "success", "agent_type": "fundamental", "version": "1.0", "timestamp": TIMESTAMP,
    "data": { "action": "buy", "confidence_score": 0.9, "reason": "Strong fundamentals." }
}
ERROR_RESPONSE_STANDARD = {
    "status": "error", "agent_type": "technical", "version": "2.0", "timestamp": TIMESTAMP,
    "error": {"code": 500, "message": "Agent failed to process"},
    "data": {"action": "hold", "confidence_score": 0.0, "reason": "N/A"}
}
UNNORMALIZABLE_RESPONSE = {"detail": "This response is invalid"}

@pytest.fixture(autouse=True)
def mock_clients():
    """
    Fixture to mock both DatabaseAgentClient and ExecutionAgentClient
    for all endpoint tests in this module.
    """
    with patch("app.main.DatabaseAgentClient") as mock_db, \
         patch("app.main.ExecutionAgentClient") as mock_exec:

        # Mock DatabaseAgentClient for portfolio data
        db_instance = mock_db.return_value.__aenter__.return_value
        db_instance.get_account_balance.return_value = AccountBalance(cash_balance=Decimal("10000.0"))
        db_instance.get_positions.return_value = []

        # Mock ExecutionAgentClient for trade submission
        exec_instance = mock_exec.return_value.__aenter__.return_value
        mock_order_response = ExecutionCreateOrderResponse(
            status="PENDING",
            order_id="EXEC-ORDER-MOCK-123",
            client_order_id=uuid.uuid4()
        )
        exec_instance.create_order.return_value = mock_order_response

        yield {
            "db_client": mock_db,
            "exec_client": mock_exec
        }

# --- Endpoint Test Cases ---

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
    mock_call_agents.return_value = (ERROR_RESPONSE_STANDARD, SUCCESS_FUND_RESPONSE)
    response = client.post("/analyze", json={"ticker": "GOOGL"})
    assert response.status_code == 200
    data = response.json()
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
    assert data["details"]["fundamental"] is None
    assert data["details"]["technical"]["action"] == "buy"

@patch('app.main.call_agents', new_callable=AsyncMock)
def test_analyze_both_agents_return_unnormalizable_data(mock_call_agents):
    """Test 500 error when both agents provide malformed responses."""
    mock_call_agents.return_value = (UNNORMALIZABLE_RESPONSE, UNNORMALIZABLE_RESPONSE)
    response = client.post("/analyze", json={"ticker": "GOOGL"})
    assert response.status_code == 500
    assert "Both Technical and Fundamental Agents failed" in response.json()["detail"]

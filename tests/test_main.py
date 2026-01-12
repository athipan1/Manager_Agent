from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
import pytest
import datetime
from decimal import Decimal

from app.main import app
from app.models import AccountBalance, CreateOrderResponse, Order, CreateOrderBody
from app.database_client import DatabaseAgentClient

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
def mock_db_client():
    """Fixture to mock the DatabaseAgentClient for all endpoint tests in this module."""
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
    assert data["details"]["fundamental"] is None # Normalization returned None
    assert data["details"]["technical"]["action"] == "buy"

@patch('app.main.call_agents', new_callable=AsyncMock)
def test_analyze_both_agents_return_unnormalizable_data(mock_call_agents):
    """Test 500 error when both agents provide malformed responses."""
    mock_call_agents.return_value = (UNNORMALIZABLE_RESPONSE, UNNORMALIZABLE_RESPONSE)
    response = client.post("/analyze", json={"ticker": "GOOGL"})
    assert response.status_code == 500
    assert "Both Technical and Fundamental Agents failed" in response.json()["detail"]

# --- Unit Test for Database Client ---

@pytest.mark.asyncio
async def test_database_client_create_order_payload():
    """
    Unit test to verify that the DatabaseAgentClient sends the correct payload
    for creating an order, ensuring 'order_type' is present.
    """
    # Arrange: Instantiate a real client, but patch its _post method
    with patch.object(DatabaseAgentClient, '_post', new_callable=AsyncMock) as mock_post:
        # Configure the mock to return a valid dictionary on await
        mock_post.return_value = {"order_id": 999, "status": "mocked_pending"}

        client_under_test = DatabaseAgentClient()
        order_body = CreateOrderBody(
            client_order_id="test-uuid-123",
            symbol="TEST",
            order_type="BUY",
            quantity=15,
            price=Decimal("123.45")
        )

        # Act: Call the method to be tested
        response = await client_under_test.create_order(account_id=1, order_body=order_body, correlation_id="corr-id-abc")

        # Assert: Check that _post was called with the correct payload
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        json_payload = call_kwargs.get('json_data', {})

        assert 'order_type' in json_payload, "The key 'order_type' should be in the payload"
        assert 'side' not in json_payload, "The key 'side' should not be in the payload"
        assert json_payload['order_type'] == "BUY"
        assert json_payload['client_order_id'] == "test-uuid-123"
        assert json_payload['quantity'] == 15

        # Assert: Check that the response is correctly parsed
        assert isinstance(response, CreateOrderResponse)
        assert response.order_id == 999
        assert response.status == "mocked_pending"

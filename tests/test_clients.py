import pytest
from unittest.mock import patch, AsyncMock
import datetime

from app.database_client import DatabaseAgentClient
from app.resilient_client import ResilientAgentClient, AgentUnavailable
from app.config import DATABASE_AGENT_URL
from httpx import TimeoutException, Response

@pytest.fixture
def mock_config():
    """Fixture to mock the API key for testing."""
    with patch('os.getenv') as mock_getenv:
        mock_getenv.return_value = 'test-api-key'
        yield mock_getenv

@pytest.mark.asyncio
async def test_database_client_sends_api_key_header(mock_config):
    """
    Verify that the DatabaseAgentClient initializes the HTTP client with the correct X-API-KEY header.
    """
    with patch("app.resilient_client.httpx.AsyncClient") as mock_async_client:
        # This will trigger the __init__ chain and instantiate the mocked client
        client = DatabaseAgentClient()

        # Assert that the underlying httpx client was initialized with the correct header
        mock_async_client.assert_called_once()
        constructor_kwargs = mock_async_client.call_args.kwargs
        assert "headers" in constructor_kwargs
        assert constructor_kwargs["headers"]["X-API-KEY"] == "test-api-key"

@pytest.mark.asyncio
async def test_resilient_client_circuit_breaker_opens_after_failures():
    """
    Verify that the ResilientAgentClient's circuit breaker opens after the configured
    number of failures and raises AgentUnavailable immediately without sending a request.
    """
    client = ResilientAgentClient(
        base_url="http://test-agent:8000",
        failure_threshold=2,
        cooldown_period=10
    )

    # Mock the internal httpx client to simulate failures
    with patch.object(client, '_client') as mock_client:
        mock_client.request.side_effect = TimeoutException("Connection failed")

        # First two calls should fail and trigger the breaker
        for _ in range(2):
            with pytest.raises(AgentUnavailable):
                await client._get("/test", "corr-id-1")

        # Verify the breaker is open
        assert client._circuit_state == "OPEN"

        # This call should fail immediately without attempting a request
        with pytest.raises(AgentUnavailable):
            await client._get("/test", "corr-id-2")

        # Assert that the request was only called twice (the initial failures)
        assert mock_client.request.call_count == 2

from uuid import uuid4
from decimal import Decimal
import respx
from app.models import CreateOrderRequest, CreateOrderResponse, OrderSide, OrderType, OrderStatus

@pytest.mark.asyncio
@respx.mock
async def test_database_client_create_order(mock_config):
    """
    Verify that the DatabaseAgentClient can successfully create an order.
    """
    client = DatabaseAgentClient()
    correlation_id = str(uuid4())
    client_order_id = str(uuid4())
    order_request = CreateOrderRequest(
        client_order_id=client_order_id,
        account_id=1,
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        price=Decimal("150.00"),
    )
    mock_order_id = 12345

    respx.post(f"{DATABASE_AGENT_URL}/accounts/1/orders").mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "agent_type": "database",
                "version": "1.0",
                "timestamp": datetime.datetime.now().isoformat(),
                "data": {
                    "order_id": mock_order_id,
                    "client_order_id": client_order_id,
                    "status": "pending",
                }
            },
        )
    )

    response = await client.create_order(1, order_request, correlation_id)

    assert isinstance(response, CreateOrderResponse)
    assert response.status == OrderStatus.PENDING
    assert response.order_id == str(mock_order_id)
    assert response.client_order_id == client_order_id

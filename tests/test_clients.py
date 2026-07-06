import pytest
from unittest.mock import patch, AsyncMock
import datetime

from app.database_client import DatabaseAgentClient
from app.resilient_client import ResilientAgentClient, AgentUnavailable
from app.config import DATABASE_AGENT_URL
from httpx import TimeoutException, Response, Request

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
        client = DatabaseAgentClient()
        mock_async_client.assert_called_once()
        constructor_kwargs = mock_async_client.call_args.kwargs
        assert "headers" in constructor_kwargs
        assert constructor_kwargs["headers"]["X-API-KEY"] == "test-api-key"

@pytest.mark.asyncio
async def test_resilient_client_circuit_breaker_opens_after_failures():
    client = ResilientAgentClient(
        base_url="http://test-agent:8000",
        failure_threshold=2,
        cooldown_period=10
    )

    with patch.object(client, '_client') as mock_client:
        mock_client.request.side_effect = TimeoutException("Connection failed")

        with pytest.raises(AgentUnavailable):
            await client._get("/test", "corr-id-1")

        with pytest.raises(AgentUnavailable):
            await client._get("/test", "corr-id-1")

        assert client._circuit_state == "OPEN"

        with pytest.raises(AgentUnavailable):
            await client._get("/test", "corr-id-2")

        assert [call.args[:2] for call in mock_client.request.call_args_list] == [
            ("GET", "/test"),
            ("GET", "/test"),
            ("GET", "/health"),
            ("GET", "/health"),
        ]

@pytest.mark.asyncio
async def test_resilient_client_recovers_open_circuit_after_health_probe():
    client = ResilientAgentClient(
        base_url="http://test-agent:8000",
        failure_threshold=1,
        cooldown_period=300,
    )
    client._circuit_state = "OPEN"
    client._failure_count = 1
    client._last_failure_time = datetime.datetime.now().timestamp()

    health_response = Response(
        200,
        json={"status": "success", "data": {"status": "healthy"}},
        request=Request("GET", "http://test-agent:8000/health"),
    )
    request_response = Response(
        200,
        json={"status": "success", "data": {"ok": True}},
        request=Request("GET", "http://test-agent:8000/real-request"),
    )

    with patch.object(client, '_client') as mock_client:
        mock_client.headers = {}
        mock_client.request = AsyncMock(side_effect=[health_response, request_response])
        response = await client._get("/real-request", "corr-id-recovered")

    assert response == {"status": "success", "data": {"ok": True}}
    assert client._circuit_state == "CLOSED"
    assert client._failure_count == 0
    assert mock_client.request.call_args_list[0].args[:2] == ("GET", "/health")
    assert mock_client.request.call_args_list[1].args[:2] == ("GET", "/real-request")

from uuid import uuid4
from decimal import Decimal
import respx
from app.models import CreateOrderRequest, CreateOrderResponse, OrderSide, OrderType, OrderStatus

@pytest.mark.asyncio
@respx.mock
async def test_database_client_create_order(mock_config):
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
        risk_approval_id="approval-test-1",
        final_quantity=10,
        guard_plan={"symbol": "AAPL", "side": "sell", "quantity": 10, "trigger_price": 140},
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

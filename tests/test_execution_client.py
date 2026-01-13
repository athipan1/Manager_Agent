import pytest
import respx
from httpx import Response
from uuid import uuid4
from decimal import Decimal

from app.models import CreateOrderRequest, CreateOrderResponse
from app.execution_client import ExecutionAgentClient, AgentUnavailable
from app.resilient_client import ResilientAgentClient
from tests.mock_static_config import EXECUTION_AGENT_URL

# Mark all tests in this file as asyncio
pytestmark = pytest.mark.asyncio


from app import config as app_config

@pytest.fixture
def execution_client(monkeypatch):
    """
    Provides an instance of the ExecutionAgentClient with mocked config values.
    """
    # Use monkeypatch to temporarily set the config values for the duration of the test
    monkeypatch.setattr(app_config, "EXECUTION_AGENT_URL", "http://mock-execution-agent")
    monkeypatch.setattr(app_config, "EXECUTION_API_KEY", "mock_api_key")

    # Now, when ExecutionAgentClient is instantiated, it will use the mocked values
    client = ExecutionAgentClient()
    return client


@respx.mock
async def test_create_order_success(execution_client: ExecutionAgentClient):
    """
    Test successful order creation with a PENDING status.
    """
    mock_order_id = "EXEC-ORDER-123"
    client_order_id = uuid4()
    correlation_id = str(uuid4())

    order_request = CreateOrderRequest(
        symbol="AAPL",
        side="buy",
        quantity=Decimal("10.5"),
        price=Decimal("150.00"),
        client_order_id=client_order_id,
    )

    mock_response = CreateOrderResponse(
        status="PENDING",
        order_id=mock_order_id,
        client_order_id=client_order_id,
    )

    # Mock the POST request to the execution agent
    respx.post(f"{EXECUTION_AGENT_URL}/orders").mock(
        return_value=Response(200, json=mock_response.model_dump(mode='json'))
    )

    async with execution_client as client:
        response = await client.create_order(order_request, correlation_id)

    assert isinstance(response, CreateOrderResponse)
    assert response.status == "PENDING"
    assert response.order_id == mock_order_id
    assert response.client_order_id == client_order_id


@respx.mock
async def test_create_order_agent_unavailable(execution_client: ExecutionAgentClient):
    """
    Test that AgentUnavailable exception is caught and handled correctly.
    """
    correlation_id = str(uuid4())
    order_request = CreateOrderRequest(
        symbol="GOOG", side="sell", quantity=Decimal("5"), price=Decimal("2800.00"), client_order_id=uuid4()
    )

    # Mock a server error (500) to trigger the retry and circuit breaker logic
    respx.post(f"{EXECUTION_AGENT_URL}/orders").mock(
        side_effect=Response(500)
    )

    # Temporarily reduce retries for faster test execution
    execution_client._max_retries = 2

    async with execution_client as client:
        response = await client.create_order(order_request, correlation_id)

    assert isinstance(response, dict)
    assert response["status"] == "error"
    assert response["reason"] == "Execution Agent unavailable"

@respx.mock
async def test_create_order_unexpected_error(execution_client: ExecutionAgentClient, monkeypatch):
    """
    Test handling of non-HTTP, unexpected errors during order creation.
    """
    correlation_id = str(uuid4())
    order_request = CreateOrderRequest(
        symbol="TSLA", side="buy", quantity=Decimal("2"), price=Decimal("700.00"), client_order_id=uuid4()
    )

    # Mock an unexpected exception during the _post call
    async def mock_post(*args, **kwargs):
        raise ValueError("Something went wrong")

    monkeypatch.setattr(execution_client, "_post", mock_post)

    async with execution_client as client:
        response = await client.create_order(order_request, correlation_id)

    assert isinstance(response, dict)
    assert response["status"] == "error"
    assert "An unexpected error occurred: Something went wrong" in response["reason"]

import pytest
import respx
from httpx import Response
from uuid import uuid4
from decimal import Decimal

from app.execution_client import ExecutionAgentClient
from app.models import CreateOrderRequest, CreateOrderResponse, OrderSide, OrderType, OrderStatus
from app.resilient_client import AgentUnavailable
from app import config as app_config

# Mark all tests in this module as asyncio
pytestmark = pytest.mark.asyncio


@pytest.fixture
def execution_client(monkeypatch):
    """
    Fixture to create an ExecutionAgentClient with a mocked base URL.
    """
    monkeypatch.setattr(app_config, "EXECUTION_AGENT_URL", "http://mock-execution-agent")
    monkeypatch.setattr(app_config, "EXECUTION_API_KEY", "mock_api_key")
    return ExecutionAgentClient()


@respx.mock
async def test_create_order_success(execution_client: ExecutionAgentClient):
    """
    Test successful order creation with a PENDING status.
    """
    mock_order_id = 12345
    client_order_id = str(uuid4())
    correlation_id = str(uuid4())

    order_request = CreateOrderRequest(
        client_order_id=client_order_id,
        account_id=1,
        symbol="AAPL",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("10"),
        price=Decimal("150.00"),
    )

    # Mock the HTTP POST request to the execution agent
    respx.post("http://mock-execution-agent/orders").mock(
        return_value=Response(
            200,
            json={
                "order_id": mock_order_id,
                "client_order_id": client_order_id,
                "status": "pending",
            },
        )
    )

    response = await execution_client.create_order(order_request, correlation_id)

    assert isinstance(response, CreateOrderResponse)
    assert response.status == OrderStatus.PENDING
    assert response.order_id == mock_order_id
    assert response.client_order_id == client_order_id


@respx.mock
async def test_create_order_agent_unavailable(execution_client: ExecutionAgentClient):
    """
    Test that AgentUnavailable exception is caught and handled correctly.
    """
    correlation_id = str(uuid4())
    order_request = CreateOrderRequest(
        client_order_id=str(uuid4()),
        account_id=1,
        symbol="GOOG",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("5"),
    )

    # Mock the route to be unavailable
    respx.post("http://mock-execution-agent/orders").mock(side_effect=AgentUnavailable)

    response = await execution_client.create_order(order_request, correlation_id)

    assert response["status"] == "error"
    assert response["reason"] == "Execution Agent unavailable"


@respx.mock
async def test_create_order_unexpected_error(execution_client: ExecutionAgentClient, monkeypatch):
    """
    Test handling of non-HTTP, unexpected errors during order creation.
    """
    correlation_id = str(uuid4())
    order_request = CreateOrderRequest(
        client_order_id=str(uuid4()),
        account_id=1,
        symbol="TSLA",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("2"),
        price=Decimal("700.00"),
    )

    # Mock the internal _post method to raise a generic exception
    async def mock_post(*args, **kwargs):
        raise ValueError("Something went wrong")

    monkeypatch.setattr(execution_client, "_post", mock_post)

    response = await execution_client.create_order(order_request, correlation_id)

    assert response["status"] == "error"
    assert "An unexpected error occurred" in response["reason"]

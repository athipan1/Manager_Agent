import pytest
import respx
from httpx import Response
from uuid import uuid4
from decimal import Decimal
import datetime

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


def order_request(**overrides):
    data = {
        "client_order_id": str(uuid4()),
        "account_id": 1,
        "symbol": "AAPL",
        "side": OrderSide.BUY,
        "order_type": OrderType.LIMIT,
        "quantity": Decimal("10"),
        "price": Decimal("150.00"),
        "risk_approval_id": "approval-test-1",
        "final_quantity": 10,
        "guard_plan": {"symbol": "AAPL", "side": "sell", "quantity": 10, "trigger_price": 140},
    }
    data.update(overrides)
    return CreateOrderRequest(**data)


@respx.mock
async def test_create_order_success(execution_client: ExecutionAgentClient):
    """
    Test successful order creation with a PENDING status.
    """
    mock_order_id = 12345
    client_order_id = str(uuid4())
    correlation_id = str(uuid4())

    request = order_request(client_order_id=client_order_id)

    # Mock the HTTP POST request to the execution agent
    respx.post("http://mock-execution-agent/execute").mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "agent_type": "execution",
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

    response = await execution_client.create_order(request, correlation_id)

    assert isinstance(response, CreateOrderResponse)
    assert response.status == OrderStatus.PENDING
    assert response.order_id == str(mock_order_id)
    assert response.client_order_id == client_order_id


@respx.mock
async def test_create_order_agent_unavailable(execution_client: ExecutionAgentClient):
    """
    Test that AgentUnavailable exception is raised.
    """
    correlation_id = str(uuid4())
    request = order_request(
        symbol="GOOG",
        side=OrderSide.SELL,
        order_type=OrderType.MARKET,
        quantity=Decimal("5"),
        price=None,
        final_quantity=5,
        guard_plan={"symbol": "GOOG", "side": "buy", "quantity": 5, "trigger_price": 120},
    )

    # Mock the route to be unavailable
    respx.post("http://mock-execution-agent/execute").mock(side_effect=AgentUnavailable("Agent down"))

    with pytest.raises(AgentUnavailable):
        await execution_client.create_order(request, correlation_id)


@respx.mock
async def test_create_order_unexpected_error(execution_client: ExecutionAgentClient, monkeypatch):
    """
    Test handling of non-HTTP, unexpected errors during order creation.
    """
    correlation_id = str(uuid4())
    request = order_request(
        symbol="TSLA",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("2"),
        price=Decimal("700.00"),
        final_quantity=2,
        guard_plan={"symbol": "TSLA", "side": "sell", "quantity": 2, "trigger_price": 650},
    )

    # Mock the internal _post method to raise a generic exception
    async def mock_post(*args, **kwargs):
        raise ValueError("Something went wrong")

    monkeypatch.setattr(execution_client, "_post", mock_post)

    with pytest.raises(ValueError):
        await execution_client.create_order(request, correlation_id)

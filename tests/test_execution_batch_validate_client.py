import datetime
from decimal import Decimal
from uuid import uuid4

import pytest
import respx
from httpx import Response

from app import config as app_config
from app.execution_client import ExecutionAgentClient
from app.models import CreateOrderRequest, OrderSide, OrderType

pytestmark = pytest.mark.asyncio


@pytest.fixture
def execution_client(monkeypatch):
    monkeypatch.setattr(app_config, "EXECUTION_AGENT_URL", "http://mock-execution-agent")
    monkeypatch.setattr(app_config, "EXECUTION_API_KEY", "mock_api_key")
    return ExecutionAgentClient()


def order_request(**overrides):
    data = {
        "client_order_id": str(uuid4()),
        "account_id": 1,
        "symbol": "KO",
        "side": OrderSide.BUY,
        "order_type": OrderType.MARKET,
        "quantity": Decimal("1"),
        "price": Decimal("60.00"),
        "risk_approval_id": "risk-ko",
        "final_quantity": 1,
        "strategy_bucket": "core_dividend",
        "guard_plan": {"symbol": "KO", "side": "sell", "quantity": 1, "trigger_price": 55},
    }
    data.update(overrides)
    return CreateOrderRequest(**data)


@respx.mock
async def test_validate_order_batch_calls_execution_endpoint(execution_client):
    correlation_id = str(uuid4())
    route = respx.post("http://mock-execution-agent/execute/batch/validate").mock(
        return_value=Response(
            200,
            json={
                "status": "success",
                "agent_type": "execution-agent",
                "version": "1.0.0",
                "timestamp": datetime.datetime.now().isoformat(),
                "data": {"approved": True, "summary": {"order_count": 1}},
            },
        )
    )

    response = await execution_client.validate_order_batch([order_request()], correlation_id)

    assert route.called is True
    assert response.data["approved"] is True
    sent = route.calls.last.request.content.decode()
    assert "strategy_bucket" in sent
    assert "core_dividend" in sent

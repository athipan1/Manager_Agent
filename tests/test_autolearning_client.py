import pytest
import httpx
from unittest.mock import patch, MagicMock

from app.autolearning_client import AutoLearningAgentClient, AutoLearningRequestBody, AgentSignal

# --- Test Data ---

@pytest.fixture
def sample_trade_data():
    """Provides a sample AutoLearningRequestBody for tests."""
    return AutoLearningRequestBody(
        trade_id="test-trade-123",
        symbol="NVDA",
        decision="buy",
        pnl_percentage=1.5,
        agent_signals=[
            AgentSignal(agent_name="technical", signal="buy", confidence=0.8)
        ]
    )

# --- Tests ---

@patch('app.autolearning_client.config_manager')
@pytest.mark.asyncio
async def test_trigger_learning_cycle_success(mock_config, sample_trade_data, respx_mock):
    """
    Test a successful call to the auto-learning agent.
    """
    mock_config.get.return_value = "http://mock-auto-learning-agent"
    mock_response = {
        "learning_state": "learning",
        "version": "1.0",
        "policy_deltas": {"risk_per_trade": 0.001}
    }
    respx_mock.post("http://mock-auto-learning-agent/learn").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    client = AutoLearningAgentClient()
    response = await client.trigger_learning_cycle(sample_trade_data)

    assert response is not None
    assert response.learning_state == "learning"
    assert response.policy_deltas.risk_per_trade == 0.001

@patch('app.autolearning_client.config_manager')
@pytest.mark.asyncio
async def test_trigger_learning_cycle_http_error(mock_config, sample_trade_data, respx_mock):
    """
    Test the client's behavior on an HTTP 500 error.
    """
    mock_config.get.return_value = "http://mock-auto-learning-agent"
    respx_mock.post("http://mock-auto-learning-agent/learn").mock(
        return_value=httpx.Response(500)
    )

    client = AutoLearningAgentClient()
    response = await client.trigger_learning_cycle(sample_trade_data)

    assert response is None

@patch('app.autolearning_client.config_manager')
@pytest.mark.asyncio
async def test_trigger_learning_cycle_timeout(mock_config, sample_trade_data, respx_mock):
    """
    Test the client's behavior on a network timeout.
    """
    mock_config.get.return_value = "http://mock-auto-learning-agent"
    def raise_timeout(request):
        raise httpx.TimeoutException("Timeout!")

    respx_mock.post("http://mock-auto-learning-agent/learn").mock(side_effect=raise_timeout)

    client = AutoLearningAgentClient()
    response = await client.trigger_learning_cycle(sample_trade_data)

    assert response is None

@patch('app.autolearning_client.config_manager')
@pytest.mark.asyncio
async def test_trigger_learning_cycle_invalid_response(mock_config, sample_trade_data, respx_mock):
    """
    Test the client's behavior with a malformed response from the agent.
    """
    mock_config.get.return_value = "http://mock-auto-learning-agent"
    mock_response = {"some_unexpected_key": "some_value"}
    respx_mock.post("http://mock-auto-learning-agent/learn").mock(
        return_value=httpx.Response(200, json=mock_response)
    )

    client = AutoLearningAgentClient()
    response = await client.trigger_learning_cycle(sample_trade_data)

    assert response is None

@patch('app.autolearning_client.config_manager')
@pytest.mark.asyncio
async def test_client_skips_if_url_is_not_configured(mock_config, sample_trade_data):
    """
    Test that the client does nothing if the agent URL is not set.
    """
    mock_config.get.return_value = None

    client = AutoLearningAgentClient()
    response = await client.trigger_learning_cycle(sample_trade_data)

    assert response is None

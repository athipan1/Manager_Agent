import pytest
from unittest.mock import patch, AsyncMock

from app.database_client import DatabaseAgentClient
from app.resilient_client import ResilientAgentClient, AgentUnavailable
from app.config import DATABASE_AGENT_URL
from httpx import TimeoutException

@pytest.fixture
def mock_config():
    """Fixture to mock the API key for testing."""
    with patch('os.getenv') as mock_getenv:
        mock_getenv.return_value = 'test-api-key'
        yield mock_getenv

@pytest.mark.asyncio
async def test_database_client_sends_api_key_header(mock_config):
    """
    Verify that the DatabaseAgentClient includes the X-API-KEY header in its requests.
    """
    with patch("app.resilient_client.ResilientAgentClient._get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = {"cash_balance": 1000}

        client = DatabaseAgentClient()
        await client.get_account_balance(account_id=1, correlation_id="test-corr-id")

        mock_get.assert_called_once()
        request_headers = mock_get.call_args.kwargs["headers"]
        assert "X-API-KEY" in request_headers
        assert request_headers["X-API-KEY"] == "test-api-key"

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

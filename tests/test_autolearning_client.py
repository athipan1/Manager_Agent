
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
from httpx import Response

# Patch os.makedirs *before* importing the application modules that use it.
patch('os.makedirs').start()

from app.autolearning_client import AutoLearningAgentClient
from app.models import PortfolioMetrics, Trade

# --- Constants for Mock Data ---

FAKE_ACCOUNT_ID = 123
FAKE_SYMBOL = "TEST"
FAKE_CORRELATION_ID = "test-uuid"
LEARNING_AGENT_URL = "http://mock-learning-agent:8004/learn"

MOCK_TRADE_HISTORY = [
    {
        "timestamp": "2024-01-01T10:00:00Z",
        "action": "buy",
        "entry_price": 100.0,
        "exit_price": 105.0,
        "pnl_pct": 5.0,
        "agents": {"technical": "buy", "fundamental": "hold"},
    }
]

MOCK_PORTFOLIO_METRICS = {
    "win_rate": 0.6,
    "average_return": 1.2,
    "max_drawdown": -5.5,
    "sharpe_ratio": 0.8,
}

MOCK_AGENT_WEIGHTS = {"technical": 0.6, "fundamental": 0.4}
MOCK_RISK_PER_TRADE = 0.01

MOCK_LEARNING_AGENT_RESPONSE = {
    "learning_state": "learning",
    "agent_weight_adjustments": {"technical": 0.05, "fundamental": -0.05},
    "risk_adjustments": {"risk_per_trade": 0.001},
    "reasoning": ["Adjusting weights based on recent volatility."],
}


@pytest.fixture
def mock_db_client():
    """Fixture to create a mock DatabaseAgentClient."""
    mock = AsyncMock()
    mock.get_trade_history.return_value = [
        Trade(**t) for t in MOCK_TRADE_HISTORY
    ]
    mock.get_portfolio_metrics.return_value = PortfolioMetrics(
        **MOCK_PORTFOLIO_METRICS
    )
    return mock


@pytest.fixture
def mock_config_manager_fixture():
    """Fixture to create a mock ConfigManager."""
    mock = MagicMock()
    mock.get.side_effect = lambda key: {
        "AUTO_LEARNING_AGENT_URL": "http://mock-learning-agent:8004",
        "AGENT_WEIGHTS": MOCK_AGENT_WEIGHTS,
        "RISK_PER_TRADE": MOCK_RISK_PER_TRADE,
    }.get(key)
    return mock


@pytest.mark.asyncio
@patch("app.autolearning_client.config_manager")
async def test_trigger_learning_cycle_success(
    mock_config_manager_patch,
    mock_db_client,
    mock_config_manager_fixture,
):
    """
    Tests the successful execution of a learning cycle, verifying
    data gathering, request construction, and response translation.
    """
    # Arrange
    mock_config_manager_patch.get.side_effect = mock_config_manager_fixture.get

    client = AutoLearningAgentClient(db_client=mock_db_client)

    with respx.mock(base_url="http://mock-learning-agent:8004") as mock_http:
        # Mock the external learning agent's response
        mock_http.post("/learn").mock(
            return_value=Response(200, json=MOCK_LEARNING_AGENT_RESPONSE)
        )

        # Act
        result = await client.trigger_learning_cycle(
            FAKE_ACCOUNT_ID,
            FAKE_SYMBOL,
            FAKE_CORRELATION_ID,
        )

        # Assert
        # 1. Verify that the database client was called correctly
        mock_db_client.get_trade_history.assert_awaited_once_with(
            FAKE_ACCOUNT_ID,
            FAKE_CORRELATION_ID,
        )
        mock_db_client.get_portfolio_metrics.assert_awaited_once_with(
            FAKE_ACCOUNT_ID,
            FAKE_CORRELATION_ID,
        )

        # 2. Verify the request payload sent to the learning agent
        request = mock_http.calls.last.request
        request_payload = request.content.decode("utf-8")
        import json

        request_json = json.loads(request_payload)

        assert request_json["symbol"] == FAKE_SYMBOL
        assert len(request_json["trade_history"]) == 1
        assert request_json["portfolio_metrics"]["win_rate"] == 0.6
        assert request_json["config"]["agent_weights"]["technical"] == 0.6

        # 3. Verify the final translated response
        assert result is not None
        assert result.learning_state == "learning"
        assert result.policy_deltas.agent_weights["technical"] == 0.05
        assert result.policy_deltas.risk_per_trade == 0.001
        assert result.version == "1.0.0"


@pytest.mark.asyncio
@patch("app.autolearning_client.config_manager")
async def test__trigger_learning_cycle_http_error(
    mock_config_manager_patch,
    mock_db_client,
    mock_config_manager_fixture,
):
    """Tests that the client returns None when the learning agent returns an HTTP error."""
    # Arrange
    mock_config_manager_patch.get.side_effect = mock_config_manager_fixture.get
    client = AutoLearningAgentClient(db_client=mock_db_client)

    with respx.mock(base_url="http://mock-learning-agent:8004") as mock_http:
        mock_http.post("/learn").mock(return_value=Response(500))

        # Act
        result = await client.trigger_learning_cycle(
            FAKE_ACCOUNT_ID, FAKE_SYMBOL, FAKE_CORRELATION_ID
        )

        # Assert
        assert result is None


if __name__ == "__main__":
    unittest.main()


import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import respx
from httpx import Response

# Patch os.makedirs *before* importing the application modules that use it.
patch('os.makedirs').start()

from app.learning_client import LearningAgentClient
from app.models import Trade

# --- Constants for Mock Data ---

FAKE_ACCOUNT_ID = 123
FAKE_SYMBOL = "TEST"
FAKE_CORRELATION_ID = "test-uuid"
LEARNING_AGENT_URL = "http://mock-learning-agent:8004/learn"

from decimal import Decimal

# This mock represents the raw data returned by the database client.
MOCK_RAW_TRADE_DATA = {
    "trade_id": "test-trade-uuid",
    "account_id": "123",
    "asset_id": "TEST",
    "symbol": "TEST",
    "side": "buy",
    "quantity": Decimal("10"),
    "price": Decimal("100.0"),
    "executed_at": "2024-07-01T10:00:00Z",
    "agents": {"technical": "buy", "fundamental": "hold"},
    "pnl_pct": Decimal("0.05"),
    "entry_price": Decimal("100.0"),
    "exit_price": Decimal("105.0")
}


MOCK_PRICE_HISTORY = [
    {"timestamp": "2024-07-01T09:00:00Z", "open": 100, "high": 102, "low": 99, "close": 101, "volume": 50000}
]


MOCK_AGENT_WEIGHTS = {"technical": 0.6, "fundamental": 0.4}
# Use strings for Decimal-based config values to avoid float precision issues
MOCK_RISK_PER_TRADE = "0.01"
MOCK_MAX_POSITION_PCT = "0.20"
MOCK_STOP_LOSS_PCT = "0.03"
MOCK_LEARNING_MODE = "conservative"
MOCK_WINDOW_SIZE = 50


MOCK_LEARNING_AGENT_RESPONSE = {
    "learning_state": "learning",
    "policy_deltas": {
        "agent_weights": {"technical": 0.05},
        "risk": {"risk_per_trade": -0.001},
        "strategy_bias": {},
        "guardrails": {},
        "asset_biases": {"TEST": 0.1}
    },
    "reasoning": ["Adjusting risk down due to recent losses."],
}


@pytest.fixture
def mock_db_client():
    """Fixture to create a mock DatabaseAgentClient."""
    mock = AsyncMock()
    # Return raw trade data that mimics the DB client response
    mock.get_trade_history.return_value = [MOCK_RAW_TRADE_DATA]
    mock.get_price_history.return_value = MOCK_PRICE_HISTORY
    return mock


@pytest.fixture
def mock_config_manager_fixture():
    """Fixture to create a mock ConfigManager."""
    mock = MagicMock()
    config_values = {
        "AUTO_LEARNING_AGENT_URL": "http://mock-learning-agent:8004",
        "AGENT_WEIGHTS": MOCK_AGENT_WEIGHTS,
        "RISK_PER_TRADE": MOCK_RISK_PER_TRADE,
        "MAX_POSITION_PERCENTAGE": MOCK_MAX_POSITION_PCT,
        "STOP_LOSS_PERCENTAGE": MOCK_STOP_LOSS_PCT,
        "LEARNING_MODE": MOCK_LEARNING_MODE,
        "WINDOW_SIZE": MOCK_WINDOW_SIZE,
    }
    mock.get.side_effect = lambda key: config_values.get(key)
    return mock


@pytest.mark.asyncio
@patch("app.learning_client.config_manager")
async def test_trigger_learning_cycle_success(
    mock_config_manager_patch,
    mock_db_client,
    mock_config_manager_fixture,
):
    """
    Tests the successful execution of a learning cycle with the new contract,
    verifying data gathering, request construction, and response translation.
    """
    # Arrange
    mock_config_manager_patch.get.side_effect = mock_config_manager_fixture.get
    client = LearningAgentClient(db_client=mock_db_client)

    with respx.mock(base_url="http://mock-learning-agent:8004") as mock_http:
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
        mock_db_client.get_price_history.assert_awaited_once_with(
            FAKE_SYMBOL,
            FAKE_CORRELATION_ID,
        )

        # 2. Verify the request payload sent to the learning agent
        request = mock_http.calls.last.request
        request_payload = request.content.decode("utf-8")
        import json
        request_json = json.loads(request_payload)

        assert request_json["learning_mode"] == MOCK_LEARNING_MODE
        assert request_json["window_size"] == MOCK_WINDOW_SIZE
        assert len(request_json["trade_history"]) == 1
        assert request_json["price_history"][FAKE_SYMBOL][0]["volume"] == 50000
        assert request_json["current_policy"]["agent_weights"]["technical"] == 0.6
        assert request_json["current_policy"]["risk"]["risk_per_trade"] == MOCK_RISK_PER_TRADE

        # 3. Verify the final translated response
        assert result is not None
        assert result.learning_state == "learning"
        assert result.policy_deltas.agent_weights["technical"] == 0.05
        assert result.policy_deltas.risk_per_trade == -0.001
        assert result.policy_deltas.asset_biases["TEST"] == 0.1
        assert result.version == "2.0.0"


@pytest.mark.asyncio
@patch("app.learning_client.config_manager")
async def test_trigger_learning_cycle_http_error(
    mock_config_manager_patch,
    mock_db_client,
    mock_config_manager_fixture,
):
    """Tests that the client returns None when the learning agent returns an HTTP error."""
    # Arrange
    mock_config_manager_patch.get.side_effect = mock_config_manager_fixture.get
    client = LearningAgentClient(db_client=mock_db_client)

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

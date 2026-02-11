
import unittest
from unittest.mock import patch, MagicMock
import httpx
import pytest
from learning_agent.db_agent_client import fetch_trade_history
from learning_agent.models import Trade
from decimal import Decimal

class TestDBAgentClient(unittest.IsolatedAsyncioTestCase):
    @patch('httpx.AsyncClient.get')
    @patch('os.getenv')
    async def test_fetch_trade_history_headers_and_mapping(self, mock_getenv, mock_get):
        # Setup mocks
        def getenv_side_effect(key, default=None):
            if key == "DB_AGENT_URL":
                return "http://mock-db-agent"
            if key == "DB_AGENT_API_KEY":
                return "mock-api-key"
            return default
        mock_getenv.side_effect = getenv_side_effect

        # Mock response from Database Agent
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "status": "success",
            "data": [
                {
                    "trade_id": "1",
                    "account_id": "acc123",
                    "symbol": "BTC-USD", # Using 'symbol' to test mapping
                    "side": "buy",
                    "quantity": "1.0",
                    "entry_price": "50000.0",
                    "exit_price": "51000.0",
                    "executed_at": "2024-01-01T00:00:00Z",
                    "pnl_pct": "0.02"
                }
            ]
        }
        mock_get.return_value = mock_response

        # Call the function
        trades = await fetch_trade_history(account_id="acc123", asset_id="BTC-USD", correlation_id="test-corr-id")

        # Verify headers
        args, kwargs = mock_get.call_args
        headers = kwargs.get("headers")
        self.assertEqual(headers["X-API-KEY"], "mock-api-key")
        self.assertEqual(headers["X-Correlation-ID"], "test-corr-id")

        # Verify mapping
        self.assertEqual(len(trades), 1)
        self.assertEqual(trades[0].asset_id, "BTC-USD")
        self.assertEqual(trades[0].pnl_pct, Decimal("0.02"))

    @patch('httpx.AsyncClient.get')
    async def test_fetch_trade_history_error_handling(self, mock_get):
        # Setup mock for 404 error
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError("Not Found", request=MagicMock(), response=mock_response)
        mock_get.return_value = mock_response

        # Call the function (should handle error gracefully and return empty list)
        with patch('os.getenv', return_value="http://mock-db-agent"):
            trades = await fetch_trade_history(account_id="acc123")

        self.assertEqual(trades, [])

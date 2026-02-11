
import unittest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from learning_agent.main import app
from learning_agent.models import Trade
from decimal import Decimal
from collections import defaultdict

# Mock the database functions before the app is imported by the TestClient
mock_db_state = defaultdict(lambda: {"bull_bias": 0.0, "bear_bias": 0.0, "vol_bias": 0.0})

def mock_save_bias_state(state):
    global mock_db_state
    mock_db_state.update(state)

def mock_load_bias_state():
    global mock_db_state
    return mock_db_state

# We use patch on the main module where the functions are imported and used
db_save_patcher = patch('learning_agent.main.save_bias_state', side_effect=mock_save_bias_state)
db_load_patcher = patch('learning_agent.main.load_bias_state', side_effect=mock_load_bias_state)
db_init_patcher = patch('learning_agent.main.init_db', return_value=None)

db_save_patcher.start()
db_load_patcher.start()
db_init_patcher.start()


class TestMain(unittest.TestCase):
    def setUp(self):
        """Set up the test client and reset the mock database state for each test."""
        global mock_db_state
        mock_db_state.clear()
        self.client = TestClient(app)

    def _get_base_bias_update_request(self, asset_id, bias_delta):
        """Helper to create a valid BiasUpdateRequest body."""
        return {
            "asset_id": asset_id,
            "bias_delta": bias_delta,
            "source": "simulation",
            "timestamp": "2024-01-01T00:00:00Z"
        }

    def test_health_check(self):
        with patch('learning_agent.main.check_db_connection', return_value=True):
            response = self.client.get("/health")
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "success")
            self.assertEqual(data["agent_type"], "learning")
            self.assertEqual(data["data"], {"status": "healthy", "database": "connected"})
            self.assertIn("timestamp", data)

    def test_update_biases_single(self):
        request_body = self._get_base_bias_update_request("AAPL", {"bull_bias": 0.1})
        response = self.client.post("/learning/update-biases", json=request_body)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["data"][0]["current_bias"]["bull_bias"], 0.1)
        self.assertEqual(mock_db_state["AAPL"]["bull_bias"], 0.1)

    def test_bias_clamping(self):
        for i in range(12):
            request_body = self._get_base_bias_update_request("NVDA", {"bull_bias": 0.1})
            # Ensure timestamp is unique to avoid any potential caching issues
            request_body["timestamp"] = f"2024-01-01T00:00:{i:02d}Z"
            self.client.post("/learning/update-biases", json=request_body)

        # Send a zero-delta request to just fetch the current clamped state
        request_body = self._get_base_bias_update_request("NVDA", {"bull_bias": 0.0})
        response = self.client.post("/learning/update-biases", json=request_body)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["data"][0]["current_bias"]["bull_bias"], 1.0)
        self.assertEqual(mock_db_state["NVDA"]["bull_bias"], 1.0)

    def _create_dummy_learning_request_body(self, trades):
        """Helper to create a valid request body from Trade models."""
        request = {
            "account_id": "acc123",
            "learning_mode": "test", "window_size": 10, "trade_history": [], "price_history": {},
            "current_policy": {
                "agent_weights": {},
                "risk": {"risk_per_trade": 0.01, "max_position_pct": 0.1, "stop_loss_pct": 0.05},
                "strategy_bias": {"preferred_regime": "any"}
            }
        }
        for trade in trades:
            trade_dict = trade.model_dump()
            for key, value in trade_dict.items():
                if isinstance(value, Decimal):
                    trade_dict[key] = str(value)
            request["trade_history"].append(trade_dict)
        return request

    @patch('learning_agent.logic.fetch_trade_history', new_callable=AsyncMock)
    def test_learn_endpoint_with_mocks(self, mock_fetch_history):
        mock_fetch_history.return_value = []

        trades = [
            Trade(trade_id=str(i), account_id="acc123", asset_id="BTC-USD", side="buy", entry_price=Decimal("50000"),
                  exit_price=Decimal("51000"), quantity=Decimal("1"), executed_at="2026-01-08T09:00:00Z",
                  pnl_pct=Decimal("0.02")) for i in range(10)
        ]
        request_body = self._create_dummy_learning_request_body(trades)

        response = self.client.post("/learn", json=request_body)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["data"]["learning_state"], "success")
        mock_fetch_history.assert_called_once_with(account_id="acc123", asset_id="BTC-USD", correlation_id=None)

    @patch('learning_agent.logic.fetch_trade_history', new_callable=AsyncMock)
    def test_bias_integration_in_learn_endpoint(self, mock_fetch_history):
        # Setup: Give BTC-USD a strong positive bull_bias using the endpoint
        update_request = self._get_base_bias_update_request("BTC-USD", {"bull_bias": 0.5})
        response = self.client.post("/learning/update-biases", json=update_request)
        self.assertEqual(response.status_code, 200) # Ensure the update was successful
        self.assertEqual(mock_db_state["BTC-USD"]["bull_bias"], 0.5)

        mock_fetch_history.return_value = []

        trades = [
            Trade(trade_id=str(i), account_id="acc123", asset_id="BTC-USD", side="buy", entry_price=Decimal("50000"),
                  exit_price=Decimal("51000"), quantity=Decimal("1"), executed_at="2026-01-08T09:00:00Z",
                  pnl_pct=Decimal("0.02")) for i in range(10)
        ]
        request_body = self._create_dummy_learning_request_body(trades)

        response = self.client.post("/learn", json=request_body)
        self.assertEqual(response.status_code, 200)
        data = response.json()

        self.assertEqual(data["status"], "success")
        self.assertIn("BTC-USD", data["data"]["policy_deltas"]["asset_biases"])
        self.assertGreater(data["data"]["policy_deltas"]["asset_biases"]["BTC-USD"], 0)

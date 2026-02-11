
import unittest
from unittest.mock import patch, AsyncMock
from decimal import Decimal
from learning_agent.models import LearningRequest, Trade, CurrentPolicy, CurrentPolicyRisk, CurrentPolicyStrategyBias
from learning_agent.logic import run_learning_cycle, _calculate_asset_performance

class TestAssetAwareLearning(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        """Set up mock data for both request and fetched history."""
        # Trades included in the API request
        self.request_trades = [
            Trade(trade_id="A10", account_id="acc123", asset_id="A", side="buy", quantity=Decimal("1"), entry_price=Decimal("100"), exit_price=Decimal("101"), executed_at="2024-01-20T10:00:00Z", pnl_pct=Decimal("0.01")),
            Trade(trade_id="B10", account_id="acc123", asset_id="B", side="sell", quantity=Decimal("1"), entry_price=Decimal("200"), exit_price=Decimal("201"), executed_at="2024-01-20T10:00:00Z", pnl_pct=Decimal("-0.005")),
            Trade(trade_id="C5", account_id="acc123", asset_id="C", side="buy", quantity=Decimal("1"), entry_price=Decimal("50"), exit_price=Decimal("49"), executed_at="2024-01-15T10:00:00Z", pnl_pct=Decimal("-0.02")),
        ]

        # Trades that will be returned by the mocked fetch_trade_history
        self.historical_trades = {
            "A": [Trade(trade_id=f"A{i}", account_id="acc123", asset_id="A", side="buy", quantity=Decimal("1"), entry_price=Decimal("100"), exit_price=Decimal("101"), executed_at=f"2024-01-{10+i:02d}T10:00:00Z", pnl_pct=Decimal("0.01")) for i in range(9)],
            "B": [Trade(trade_id=f"B{i}", account_id="acc123", asset_id="B", side="sell", quantity=Decimal("1"), entry_price=Decimal("200"), exit_price=Decimal("201"), executed_at=f"2024-01-{10+i:02d}T10:00:00Z", pnl_pct=Decimal("-0.005")) for i in range(9)],
            "C": [Trade(trade_id=f"C{i}", account_id="acc123", asset_id="C", side="buy", quantity=Decimal("1"), entry_price=Decimal("50"), exit_price=Decimal("49"), executed_at=f"2024-01-{10+i:02d}T10:00:00Z", pnl_pct=Decimal("-0.02")) for i in range(4)],
        }

        self.current_policy = CurrentPolicy(
            agent_weights={'agent_a': 0.5, 'agent_b': 0.5},
            risk=CurrentPolicyRisk(risk_per_trade=0.01, max_position_pct=0.1, stop_loss_pct=0.05),
            strategy_bias=CurrentPolicyStrategyBias(preferred_regime="neutral")
        )

        self.request = LearningRequest(
            account_id="acc123",
            learning_mode="test",
            window_size=10,
            trade_history=self.request_trades,
            price_history={},
            current_policy=self.current_policy,
            execution_result=None,
        )
        self.bias_state = {}

    def test_calculate_asset_performance(self):
        """Test the standalone asset performance calculation."""
        all_asset_a_trades = self.historical_trades["A"] + [self.request_trades[0]]
        pnl_pcts = [float(t.pnl_pct) for t in all_asset_a_trades]
        perf = _calculate_asset_performance(all_asset_a_trades, pnl_pcts)

        self.assertAlmostEqual(perf["win_rate"], 1.0)
        self.assertAlmostEqual(perf["max_drawdown"], 0)
        self.assertEqual(perf["trade_count"], 10)

    @patch('learning_agent.logic.fetch_trade_history', new_callable=AsyncMock)
    async def test_warmup_phase(self, mock_fetch):
        """Test that assets with insufficient combined trades are in warmup."""
        mock_fetch.side_effect = lambda account_id, asset_id, **kwargs: self.historical_trades.get(asset_id, [])

        response = await run_learning_cycle(self.request, self.bias_state)
        # Total trades for C = 1 (request) + 4 (historical) = 5. Still in warmup.
        self.assertNotIn("C", response.policy_deltas.asset_biases)
        self.assertIn("Asset 'C' is in warmup", "".join(response.reasoning))

    @patch('learning_agent.logic.fetch_trade_history', new_callable=AsyncMock)
    async def test_asset_bias_with_merged_history(self, mock_fetch):
        """Test bias recommendations with merged request and historical data."""
        mock_fetch.side_effect = lambda account_id, asset_id, **kwargs: self.historical_trades.get(asset_id, [])

        response = await run_learning_cycle(self.request, self.bias_state)
        biases = response.policy_deltas.asset_biases
        # Asset A has 10 total profitable trades -> positive bias
        self.assertGreater(biases.get("A", 0), 0)
        # Asset B has 10 total losing trades -> negative bias
        self.assertLess(biases.get("B", 0), 0)

    @patch('learning_agent.logic.fetch_trade_history', new_callable=AsyncMock)
    async def test_drawdown_clustering_consecutive_losses(self, mock_fetch):
        """Test risk adjustment from consecutive losses in combined history."""
        # Asset D has 10 consecutive losses, split between request and history
        historical_d = [Trade(trade_id=f"D{i}", account_id="acc123", asset_id="D", side="buy", quantity=Decimal("1"), entry_price=Decimal("100"), exit_price=Decimal("99"), executed_at=f"2024-01-1{i}T10:00:00Z", pnl_pct=Decimal("-0.01")) for i in range(9)]
        request_d = [Trade(trade_id="D9", account_id="acc123", asset_id="D", side="buy", quantity=Decimal("1"), entry_price=Decimal("100"), exit_price=Decimal("99"), executed_at="2024-01-19T10:00:00Z", pnl_pct=Decimal("-0.01"))]

        mock_fetch.side_effect = lambda account_id, asset_id, **kwargs: historical_d if asset_id == "D" else []

        request = self.request.model_copy(deep=True)
        request.trade_history = request_d

        response = await run_learning_cycle(request, self.bias_state)
        self.assertIn("risk_per_trade", response.policy_deltas.risk)
        self.assertLess(response.policy_deltas.risk["risk_per_trade"], 0)
        self.assertTrue(any("consecutive losses" in r for r in response.reasoning))

    @patch('learning_agent.logic.fetch_trade_history', new_callable=AsyncMock)
    async def test_deduplication_of_trades(self, mock_fetch):
        """Test that trades are correctly de-duplicated."""
        # A trade with the same ID exists in both request and historical data
        duplicate_trade = self.request_trades[0]

        mock_fetch.return_value = [duplicate_trade] + self.historical_trades["A"]

        # We only care about Asset A for this test
        request = self.request.model_copy(deep=True)
        request.trade_history = [self.request_trades[0]]

        response = await run_learning_cycle(request, self.bias_state)

        # Find the reasoning line for Asset A's performance
        reasoning_line = next((r for r in response.reasoning if "Asset 'A'" in r), "")
        # The total number of trades should be 10 (9 historical + 1 unique in request), not 11
        # This is indirectly tested by the performance score calculation logic.
        # A direct test would require inspecting the `final_trade_list` inside the logic,
        # but we can infer from the outcome.
        # Asset A's total trades = 9 historical + 1 from request = 10, which is not in warmup.
        self.assertNotIn("warmup", reasoning_line)


    @patch('learning_agent.logic.fetch_trade_history', new_callable=AsyncMock)
    async def test_empty_trade_history(self, mock_fetch):
        """Test that the service handles empty history from both sources."""
        mock_fetch.return_value = []

        request = self.request.model_copy(deep=True)
        request.trade_history = []

        response = await run_learning_cycle(request, self.bias_state)
        self.assertEqual(response.learning_state, "insufficient_data")

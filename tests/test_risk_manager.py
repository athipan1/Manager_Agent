import unittest
from app.risk_manager import assess_trade

class TestRiskManager(unittest.TestCase):

    def test_approve_buy_order_fixed_stop(self):
        """Test a standard buy order with a fixed stop loss."""
        decision = assess_trade(
            portfolio_value=100000,
            risk_per_trade=0.01,
            fixed_stop_loss_pct=0.05,
            enable_technical_stop=False,
            max_position_pct=0.20,
            symbol="AAPL",
            action="buy",
            entry_price=150.00,
        )
        self.assertTrue(decision["approved"])
        self.assertEqual(decision["position_size"], 133)
        self.assertEqual(decision["stop_loss"], 142.5)
        self.assertEqual(decision["reason"], "Trade approved by Risk Manager.")

    def test_approve_buy_order_technical_stop(self):
        """Test a buy order using a more favorable technical stop loss."""
        decision = assess_trade(
            portfolio_value=100000,
            risk_per_trade=0.01,
            fixed_stop_loss_pct=0.05,
            enable_technical_stop=True,
            max_position_pct=0.30, # Increased to allow the trade
            symbol="AAPL",
            action="buy",
            entry_price=150.00,
            technical_stop_loss=145.00 # Higher than fixed SL of 142.5
        )
        self.assertTrue(decision["approved"])
        self.assertEqual(decision["position_size"], 200) # Smaller risk per share = larger size
        self.assertEqual(decision["stop_loss"], 145.0)

    def test_reject_buy_invalid_stop_loss(self):
        """Test rejection when the final stop loss is above the entry price."""
        decision = assess_trade(
            portfolio_value=100000,
            risk_per_trade=0.01,
            fixed_stop_loss_pct=0.05,
            enable_technical_stop=True,
            max_position_pct=0.20,
            symbol="AAPL",
            action="buy",
            entry_price=150.00,
            technical_stop_loss=151.00 # Invalid SL
        )
        self.assertFalse(decision["approved"])
        self.assertIn("must be below entry price", decision["reason"])

    def test_scale_down_buy_exceeds_max_position_value(self):
        """Test scaling down when the calculated position value is too high."""
        decision = assess_trade(
            portfolio_value=10000, # Smaller portfolio
            risk_per_trade=0.01, # 100 risk
            fixed_stop_loss_pct=0.01, # 1.5 risk/share
            enable_technical_stop=False,
            max_position_pct=0.10, # Max position is 1000
            symbol="AAPL",
            action="buy",
            entry_price=150.00,
        )
        # Ideal size = 100 / 1.5 = 66. Value = 9900.
        # Max value is 1000. New size = floor(1000 / 150) = 6.
        self.assertTrue(decision["approved"])
        self.assertEqual(decision["position_size"], 6)
        self.assertIn("scaled down", decision["reason"])

    def test_reject_buy_zero_position_size(self):
        """Test rejection when risk parameters result in a zero position size."""
        decision = assess_trade(
            portfolio_value=1000,
            risk_per_trade=0.01, # 10 risk
            fixed_stop_loss_pct=0.10,
            enable_technical_stop=False,
            max_position_pct=0.20,
            symbol="AAPL",
            action="buy",
            entry_price=150.00, # Risk per share is 15
        )
        # Position size = floor(10 / 15) = 0
        self.assertFalse(decision["approved"])
        self.assertIn("Calculated position size is 0", decision["reason"])

    def test_approve_sell_order_existing_position(self):
        """Test approval of a sell order for an existing position."""
        decision = assess_trade(
            portfolio_value=100000,
            risk_per_trade=0.01,
            fixed_stop_loss_pct=0.05,
            enable_technical_stop=False,
            max_position_pct=0.20,
            symbol="AAPL",
            action="sell",
            entry_price=155.00,
            current_position_size=100
        )
        self.assertTrue(decision["approved"])
        self.assertEqual(decision["position_size"], 100)
        self.assertEqual(decision["reason"], "Approval to sell existing position.")

    def test_reject_sell_order_no_position(self):
        """Test rejection of a sell order when there is no position."""
        decision = assess_trade(
            portfolio_value=100000,
            risk_per_trade=0.01,
            fixed_stop_loss_pct=0.05,
            enable_technical_stop=False,
            max_position_pct=0.20,
            symbol="AAPL",
            action="sell",
            entry_price=155.00,
            current_position_size=0
        )
        self.assertFalse(decision["approved"])
        self.assertEqual(decision["reason"], "Sell rejected. No existing position to sell.")

    def test_reject_invalid_action(self):
        """Test rejection for an action that is not 'buy' or 'sell'."""
        decision = assess_trade(
            portfolio_value=100000,
            risk_per_trade=0.01,
            fixed_stop_loss_pct=0.05,
            enable_technical_stop=False,
            max_position_pct=0.20,
            symbol="AAPL",
            action="hold",
            entry_price=150.00,
        )
        self.assertFalse(decision["approved"])
        self.assertIn("Invalid action", decision["reason"])

    def test_approve_short_order(self):
        """Test a standard short order approval."""
        decision = assess_trade(
            portfolio_value=100000,
            risk_per_trade=0.01,
            fixed_stop_loss_pct=0.05, # SL will be 157.5
            enable_technical_stop=False,
            max_position_pct=0.20,
            symbol="TSLA",
            action="short",
            entry_price=150.00,
        )
        self.assertTrue(decision["approved"])
        self.assertEqual(decision["position_size"], 133)
        self.assertEqual(decision["stop_loss"], 157.5)
        self.assertEqual(decision["action"], "short")

    def test_approve_cover_order(self):
        """Test a cover order for an existing short position."""
        decision = assess_trade(
            portfolio_value=100000,
            risk_per_trade=0.01,
            fixed_stop_loss_pct=0.05,
            enable_technical_stop=False,
            max_position_pct=0.20,
            symbol="TSLA",
            action="cover",
            entry_price=140.00,
            current_position_size=-100 # Negative for short
        )
        self.assertTrue(decision["approved"])
        self.assertEqual(decision["position_size"], 100)
        self.assertEqual(decision["reason"], "Approval to cover existing short position.")

    def test_reject_buy_bad_risk_reward(self):
        """Test rejection of a buy order due to a poor risk/reward ratio."""
        decision = assess_trade(
            portfolio_value=100000,
            risk_per_trade=0.01, # Risk: 1000
            fixed_stop_loss_pct=0.05, # SL: 142.5, Risk/share: 7.5
            enable_technical_stop=False,
            max_position_pct=0.20,
            symbol="AAPL",
            action="buy",
            entry_price=150.00,
            take_profit_price=155.00, # Reward/share: 5.0
            min_risk_reward_ratio=1.5 # R:R is 5/7.5 = 0.66, which is < 1.5
        )
        self.assertFalse(decision["approved"])
        self.assertIn("Risk/Reward ratio", decision["reason"])
        self.assertAlmostEqual(decision["risk_reward_ratio"], 0.67, places=2)

    def test_approve_buy_atr_stop(self):
        """Test that the ATR stop is correctly used when it's the most conservative."""
        decision = assess_trade(
            portfolio_value=100000,
            risk_per_trade=0.01,
            fixed_stop_loss_pct=0.10, # Fixed SL would be 135
            enable_technical_stop=False,
            max_position_pct=0.20,
            symbol="AAPL",
            action="buy",
            entry_price=150.00,
            atr_value=4,
            atr_multiplier=2.5 # ATR Stop = 150 - (4 * 2.5) = 140
        )
        # ATR stop of 140 is higher (tighter) than fixed stop of 135
        self.assertTrue(decision["approved"])
        self.assertEqual(decision["stop_loss"], 140)
        self.assertEqual(decision["position_size"], 100) # 1000 / (150 - 140)

if __name__ == '__main__':
    unittest.main()

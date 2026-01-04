import unittest
import os
import json
from app.risk_manager import assess_trade

class TestNewRiskManagerFeatures(unittest.TestCase):

    def setUp(self):
        """Set up for tests. Ensures log files don't exist before each test."""
        if os.path.exists("logs/assessment_history.json"):
            os.remove("logs/assessment_history.json")
        if os.path.exists("logs/assessment_history.csv"):
            os.remove("logs/assessment_history.csv")

    def tearDown(self):
        """Tear down after tests. Cleans up log files."""
        if os.path.exists("logs/assessment_history.json"):
            os.remove("logs/assessment_history.json")
        if os.path.exists("logs/assessment_history.csv"):
            os.remove("logs/assessment_history.csv")

    def test_approve_short_order(self):
        """Test a standard short order approval."""
        decision = assess_trade(
            portfolio_value=100000, risk_per_trade=0.01,
            fixed_stop_loss_pct=0.05, enable_technical_stop=False,
            max_position_pct=0.20, symbol="TSLA",
            action="short", entry_price=150.00,
        )
        self.assertTrue(decision["approved"])
        self.assertEqual(decision["position_size"], 133)
        self.assertEqual(decision["stop_loss"], 157.5)
        self.assertEqual(decision["action"], "short")

    def test_approve_cover_order(self):
        """Test a cover order for an existing short position."""
        decision = assess_trade(
            portfolio_value=100000, risk_per_trade=0.01,
            fixed_stop_loss_pct=0.05, enable_technical_stop=False,
            max_position_pct=0.20, symbol="TSLA",
            action="cover", entry_price=140.00,
            current_position_size=-100
        )
        self.assertTrue(decision["approved"])
        self.assertEqual(decision["position_size"], 100)
        self.assertEqual(decision["reason"], "Approval to cover existing short position.")

    def test_reject_buy_bad_risk_reward(self):
        """Test rejection of a buy order due to a poor risk/reward ratio."""
        decision = assess_trade(
            portfolio_value=100000, risk_per_trade=0.01,
            fixed_stop_loss_pct=0.05, enable_technical_stop=False,
            max_position_pct=0.20, symbol="AAPL",
            action="buy", entry_price=150.00,
            take_profit_price=155.00, min_risk_reward_ratio=1.5
        )
        self.assertFalse(decision["approved"])
        self.assertIn("Risk/Reward ratio", decision["reason"])

    def test_approve_buy_good_risk_reward_multiplier(self):
        """Test approval with a good R:R ratio calculated from a multiplier."""
        decision = assess_trade(
            portfolio_value=100000, risk_per_trade=0.01,
            fixed_stop_loss_pct=0.05, enable_technical_stop=False, # Risk/share = 7.5
            max_position_pct=0.20, symbol="AAPL",
            action="buy", entry_price=150.00,
            reward_multiplier=2.0, min_risk_reward_ratio=1.5 # TP = 165, Reward/share = 15, R:R = 2.0
        )
        self.assertTrue(decision["approved"])
        self.assertEqual(decision["take_profit"], 165.0)
        self.assertAlmostEqual(decision["risk_reward_ratio"], 2.0)

    def test_approve_buy_atr_stop(self):
        """Test that the ATR stop is correctly used when it's the most conservative."""
        decision = assess_trade(
            portfolio_value=100000, risk_per_trade=0.01,
            fixed_stop_loss_pct=0.10, enable_technical_stop=False, # Fixed SL = 135
            max_position_pct=0.20, symbol="AAPL",
            action="buy", entry_price=150.00,
            atr_value=4, atr_multiplier=2.5 # ATR SL = 150 - (4 * 2.5) = 140
        )
        self.assertTrue(decision["approved"])
        self.assertEqual(decision["stop_loss"], 140)

    def test_short_atr_stop(self):
        """Test ATR stop for a short position."""
        decision = assess_trade(
            portfolio_value=100000, risk_per_trade=0.01,
            fixed_stop_loss_pct=0.05, enable_technical_stop=False, # Fixed SL = 157.5
            max_position_pct=0.20, symbol="TSLA",
            action="short", entry_price=150.00,
            atr_value=3, atr_multiplier=2 # ATR SL = 150 + (3 * 2) = 156
        )
        self.assertTrue(decision["approved"])
        self.assertEqual(decision["stop_loss"], 156) # Tighter stop is chosen

    def test_logging_to_files(self):
        """Test that a decision is correctly logged to both JSON and CSV files."""
        assess_trade(
            portfolio_value=10000, risk_per_trade=0.01,
            fixed_stop_loss_pct=0.05, enable_technical_stop=False,
            max_position_pct=0.10, symbol="LOGTEST",
            action="buy", entry_price=200.00,
        )

        # Check JSON log
        self.assertTrue(os.path.exists("logs/assessment_history.json"))
        with open("logs/assessment_history.json", "r") as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 1)
            log_data = json.loads(lines[0])
            self.assertEqual(log_data["symbol"], "LOGTEST")
            self.assertTrue(log_data["approved"])

        # Check CSV log
        self.assertTrue(os.path.exists("logs/assessment_history.csv"))
        with open("logs/assessment_history.csv", "r") as f:
            lines = f.readlines()
            self.assertEqual(len(lines), 2) # Header + 1 line
            self.assertIn("timestamp,approved,reason,symbol", lines[0])
            self.assertIn("LOGTEST", lines[1])
            self.assertIn("True", lines[1])

if __name__ == '__main__':
    unittest.main()

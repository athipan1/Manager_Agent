import os
import sys
import unittest

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.rule_based_analyzer import run_rule_based_analysis  # noqa: E402


class TestRuleBasedAnalyzer(unittest.TestCase):

    def test_growth_style_strong(self):
        """Test growth style with strong data."""
        data = {"Revenue Growth": 0.15, "EPS Growth": 0.12}
        result = run_rule_based_analysis("TEST", data, "growth")
        self.assertEqual(result["strength"], "strong_buy")
        self.assertAlmostEqual(result["score"], 1.0)
        self.assertIn("Revenue Growth > 10%", result["reasoning"])
        self.assertIn("EPS Growth > 10%", result["reasoning"])

    def test_growth_style_weak(self):
        """Test growth style with weak data."""
        data = {"Revenue Growth": 0.05, "EPS Growth": -0.05}
        result = run_rule_based_analysis("TEST", data, "growth")
        self.assertEqual(result["strength"], "sell")
        self.assertAlmostEqual(result["score"], 0.3)

    def test_value_style_strong(self):
        """Test value style with strong data."""
        data = {"P/E Ratio": 12, "P/B Ratio": 0.9}
        result = run_rule_based_analysis("TEST", data, "value")
        self.assertEqual(result["strength"], "strong_buy")
        self.assertAlmostEqual(result["score"], 1.0)
        self.assertIn("P/E Ratio < 15", result["reasoning"])
        self.assertIn("P/B Ratio < 1", result["reasoning"])

    def test_value_style_weak(self):
        """Test value style with weak data."""
        data = {"P/E Ratio": 25, "P/B Ratio": 3}
        result = run_rule_based_analysis("TEST", data, "value")
        self.assertEqual(result["strength"], "sell")
        self.assertAlmostEqual(result["score"], 0.3)

    def test_dividend_style_strong(self):
        """Test dividend style with strong data."""
        data = {"Dividend Yield": 0.05, "Debt to Equity Ratio": 50}
        result = run_rule_based_analysis("TEST", data, "dividend")
        self.assertEqual(result["strength"], "strong_buy")
        self.assertAlmostEqual(result["score"], 1.0)
        self.assertIn("Dividend Yield > 4%", result["reasoning"])
        self.assertIn("Debt to Equity Ratio < 100", result["reasoning"])

    def test_dividend_style_weak(self):
        """Test dividend style with weak data."""
        data = {"Dividend Yield": 0.01, "Debt to Equity Ratio": 200}
        result = run_rule_based_analysis("TEST", data, "dividend")
        self.assertEqual(result["strength"], "sell")
        self.assertAlmostEqual(result["score"], 0.3)

    def test_unknown_style(self):
        """Test that an unknown style defaults to value analysis."""
        data = {"P/E Ratio": 10, "P/B Ratio": 0.8}
        result = run_rule_based_analysis("TEST", data, "unknown_style")
        self.assertEqual(result["strength"], "strong_buy")
        self.assertIn("หุ้นคุณค่า", result["reasoning"])


if __name__ == '__main__':
    unittest.main()

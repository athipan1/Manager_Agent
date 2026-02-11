import os
import sys
import unittest
from unittest.mock import patch

# Add the project root to the Python path before local imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.fundamental_agent import run_analysis  # noqa: E402
from app.exceptions import ModelError  # noqa: E402


class TestFundamentalAgent(unittest.TestCase):

    @patch('app.fundamental_agent.cache_handler')
    def test_analysis_cache_hit(self, mock_cache_handler):
        """Test that a cached analysis result is returned immediately."""
        print("Testing analysis cache hit...")
        mock_cache_handler.load_from_cache.return_value = {"cached": True}

        result = run_analysis("AAPL", "growth")

        self.assertTrue(result["cached"])
        mock_cache_handler.load_from_cache.assert_called_once_with("analysis_AAPL_growth")

    @patch('app.fundamental_agent.run_rule_based_analysis')
    @patch('app.fundamental_agent.analyze_financials', side_effect=ModelError("LLM failed"))
    @patch('app.fundamental_agent.get_financial_data')
    @patch('app.fundamental_agent.cache_handler')
    def test_fallback_logic_on_model_error(self, mock_cache_handler, mock_get_data, mock_analyze, mock_rule_based):
        """Test that the rule-based fallback is triggered on ModelError."""
        print("Testing fallback logic on ModelError...")
        mock_cache_handler.load_from_cache.return_value = None
        mock_get_data.return_value = {"some_data": 123}
        mock_rule_based.return_value = {"source": "rule_based"}

        result = run_analysis("MSFT", "value")

        self.assertEqual(result["source"], "rule_based")
        mock_analyze.assert_called_once()
        mock_rule_based.assert_called_once()
        mock_cache_handler.save_to_cache.assert_called_once()

    @patch('app.fundamental_agent.run_rule_based_analysis')
    @patch('app.fundamental_agent.analyze_financials')
    @patch('app.fundamental_agent.get_financial_data')
    @patch('app.fundamental_agent.cache_handler')
    def test_successful_llm_analysis(self, mock_cache_handler, mock_get_data, mock_analyze, mock_rule_based):
        """Test a successful run using the LLM analyzer without fallback."""
        print("Testing successful LLM analysis...")
        mock_cache_handler.load_from_cache.return_value = None
        mock_get_data.return_value = {"real_data": 456}
        mock_analyze.return_value = {"source": "llm"}

        result = run_analysis("GOOG", "dividend")

        self.assertEqual(result["source"], "llm")
        mock_analyze.assert_called_once()
        mock_rule_based.assert_not_called()
        mock_cache_handler.save_to_cache.assert_called_once()
        # Verify the correct data is passed to save_to_cache
        cache_key, cache_data = mock_cache_handler.save_to_cache.call_args[0]
        self.assertEqual(cache_key, "analysis_GOOG_dividend")
        self.assertEqual(cache_data["source"], "llm")


if __name__ == '__main__':
    unittest.main()

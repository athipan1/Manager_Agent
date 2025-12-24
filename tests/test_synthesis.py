import pytest
from app.synthesis import get_weighted_verdict
from unittest.mock import patch

# Test cases for the weighted verdict logic
# Format: (tech_action, tech_score, fund_action, fund_score, expected_verdict)
test_data = [
    # --- Basic Scenarios ---
    ("buy", 0.8, "buy", 0.9, "strong_buy"),  # Both strongly agree. Score: 1.0 -> strong_buy
    ("sell", 0.8, "sell", 0.9, "strong_sell"), # Both strongly agree. Score: -1.0 -> strong_sell
    ("hold", 0.8, "hold", 0.9, "hold"),       # Both agree on hold. Score: 0.0 -> hold

    # --- Conflicting Signals ---
    ("buy", 0.8, "sell", 0.5, "hold"),         # Equal weights -> Score: (1*0.5) + (-1*0.5) = 0.0 -> hold
    ("buy", 0.5, "sell", 0.8, "hold"),         # Equal weights -> Score: (1*0.5) + (-1*0.5) = 0.0 -> hold

    # --- One Agent is Neutral ---
    ("buy", 0.8, "hold", 0.5, "buy"),          # Score: (1*0.5) + (0*0.5) = 0.5 -> buy
    ("sell", 0.8, "hold", 0.5, "sell"),        # Score: (-1*0.5) + (0*0.5) = -0.5 -> sell
]

@pytest.mark.parametrize("tech_action, tech_score, fund_action, fund_score, expected", test_data)
def test_weighted_verdict_logic_default_weights(tech_action, tech_score, fund_action, fund_score, expected):
    """
    Tests the get_weighted_verdict function with default 50/50 weights.
    """
    assert get_weighted_verdict(tech_action, tech_score, fund_action, fund_score) == expected

def test_weighted_verdict_logic_dynamic_weights():
    """
    Tests the get_weighted_verdict function with dynamically adjusted weights.
    """
    # Mock the config_manager to return custom weights
    with patch('app.synthesis.config_manager') as mock_config:
        mock_config.get.return_value = {"technical": 0.8, "fundamental": 0.2}

        # Scenario: Tech says buy, Fund says sell. Tech has a much higher weight.
        # Expected score: (1 * 0.8) + (-1 * 0.2) = 0.6 -> buy
        result = get_weighted_verdict("buy", 0.9, "sell", 0.9)
        assert result == "buy"

        # Scenario: Tech says sell, Fund says buy. Tech still dominates.
        # Expected score: (-1 * 0.8) + (1 * 0.2) = -0.6 -> sell
        result = get_weighted_verdict("sell", 0.9, "buy", 0.9)
        assert result == "sell"

import pytest
from app.synthesis import get_weighted_verdict, get_reasons

# Test data for various scenarios
# Format: (tech_action, tech_score, fund_action, fund_score, expected_verdict)
# Note: The expected verdicts have been updated to match the simplified logic.
test_data = [
    # Agreement Scenarios
    ("buy", 0.8, "buy", 0.9, "buy"),
    ("sell", 0.8, "sell", 0.9, "sell"),
    ("hold", 0.8, "hold", 0.9, "hold"),
    ("buy", 0.9, "buy", 0.5, "buy"),
    ("buy", 0.5, "buy", 0.9, "buy"),

    # Conflict Scenarios
    ("buy", 0.8, "sell", 0.5, "buy"),
    ("buy", 0.5, "sell", 0.8, "sell"),
    ("buy", 0.7, "sell", 0.7, "hold"),

    # Hold Scenarios
    ("buy", 0.8, "hold", 0.5, "buy"),
    ("buy", 0.4, "hold", 0.9, "hold"),
    ("sell", 0.8, "hold", 0.5, "sell"),
    ("sell", 0.4, "hold", 0.9, "hold"),

    # Edge Cases
    ("buy", 0.0, "sell", 0.0, "hold"),
    ("buy", 0.1, "sell", 0.9, "sell"),
    ("buy", 0.9, "sell", 0.1, "buy"),
]


@pytest.mark.parametrize("tech_action, tech_score, fund_action, fund_score, expected", test_data)
def test_weighted_verdict_logic(tech_action, tech_score, fund_action, fund_score, expected):
    """
    Tests the get_weighted_verdict function with various scenarios,
    including agreements, conflicts, and different confidence levels.
    """
    assert get_weighted_verdict(tech_action, tech_score, fund_action, fund_score) == expected


def test_get_reasons():
    """
    Tests that the get_reasons function returns the correct descriptive strings
    for each action.
    """
    tech_reason, fund_reason = get_reasons("buy", "sell")
    assert "Technical analysis suggests a buy" in tech_reason
    assert "Fundamental analysis suggests a sell" in fund_reason

    tech_reason, fund_reason = get_reasons("hold", "hold")
    assert "Technical analysis suggests a hold" in tech_reason
    assert "Fundamental analysis suggests a hold" in fund_reason

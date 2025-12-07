import pytest
from app.synthesis import get_final_verdict

# Test cases for the decision matrix logic
# Format: (technical_action, fundamental_action, expected_verdict)
test_data = [
    ("buy", "buy", "Strong Buy"),
    ("buy", "hold", "Accumulate"),
    ("buy", "sell", "Speculative Buy"),
    ("hold", "buy", "Value Buy"),
    ("hold", "hold", "Hold"),
    ("hold", "sell", "Review Fundamentals"),
    ("sell", "buy", "Contrarian Buy"),
    ("sell", "hold", "Wait and See"),
    ("sell", "sell", "Strong Sell"),
    # Edge cases
    ("unknown", "buy", "Indeterminate"),
    ("buy", "unknown", "Indeterminate"),
    ("unknown", "unknown", "Indeterminate"),
]

@pytest.mark.parametrize("tech_action, fund_action, expected", test_data)
def test_decision_matrix(tech_action, fund_action, expected):
    """Tests all combinations in the decision matrix."""
    assert get_final_verdict(tech_action, fund_action) == expected

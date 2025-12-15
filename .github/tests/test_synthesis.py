import pytest
from app.synthesis import get_weighted_verdict

# Test cases for the weighted verdict logic
# Format: (tech_action, tech_score, fund_action, fund_score, expected_verdict)
test_data = [
    # --- Basic Scenarios ---
    ("buy", 0.8, "buy", 0.9, "Strong Buy"),  # Both strongly agree
    ("sell", 0.8, "sell", 0.9, "Strong Sell"), # Both strongly agree
    ("hold", 0.8, "hold", 0.9, "Hold"),       # Both agree on hold

    # --- High Confidence Agreement ---
    ("buy", 0.9, "buy", 0.5, "Strong Buy"),  # Tech is more confident
    ("buy", 0.5, "buy", 0.9, "Strong Buy"),  # Fund is more confident

    # --- Conflicting Signals ---
    # Tech says buy, Fund says sell
    ("buy", 0.8, "sell", 0.5, "Hold"),         # Tech's buy is stronger, but not enough to overcome sell. Score: ~0.23 -> Hold
    ("buy", 0.5, "sell", 0.8, "Hold"),         # Fund's sell is stronger, but not enough to overcome buy. Score: ~-0.23 -> Hold
    ("buy", 0.7, "sell", 0.7, "Hold"),         # Equal confidence -> Hold

    # --- One Agent is Neutral ---
    # Tech says buy, Fund says hold
    ("buy", 0.8, "hold", 0.5, "Buy"),          # Tech's buy signal dominates. Score: ~0.61 -> Buy
    ("buy", 0.4, "hold", 0.9, "Buy"),          # Fund's hold is strong, but tech's buy is enough to tip it. Score: ~0.307 -> Buy
    # Tech says sell, Fund says hold
    ("sell", 0.8, "hold", 0.5, "Sell"),        # Tech's sell signal dominates. Score: ~-0.61 -> Sell
    ("sell", 0.4, "hold", 0.9, "Sell"),        # Fund's hold is strong, but tech's sell is enough to tip it. Score: ~-0.307 -> Sell

    # --- Edge Cases ---
    ("buy", 0.0, "sell", 0.0, "Indeterminate"), # Zero scores
    ("buy", 0.1, "sell", 0.9, "Strong Sell"),   # Fund heavily outweighs tech
    ("buy", 0.9, "sell", 0.1, "Strong Buy"),    # Tech heavily outweighs fund
]

@pytest.mark.parametrize("tech_action, tech_score, fund_action, fund_score, expected", test_data)
def test_weighted_verdict_logic(tech_action, tech_score, fund_action, fund_score, expected):
    """
    Tests the get_weighted_verdict function with various scenarios,
    including agreements, conflicts, and different confidence levels.
    """
    assert get_weighted_verdict(tech_action, tech_score, fund_action, fund_score) == expected
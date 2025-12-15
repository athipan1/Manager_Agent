from typing import Tuple

REASON_MAPPING = {
    "technical": {
        "buy": "RSI indicates oversold conditions and buying momentum is increasing.",
        "sell": "RSI is overbought and trend indicators show signs of reversal.",
        "hold": "Market indicators are neutral; no clear buy or sell signal.",
    },
    "fundamental": {
        "buy": "Company shows strong fundamentals and is undervalued.",
        "sell": "Weak fundamentals or overvalued stock price.",
        "hold": "Solid fundamentals but the current price is fair; limited upside.",
    }
}


def get_weighted_verdict(
    technical_action: str,
    technical_score: float,
    fundamental_action: str,
    fundamental_score: float,
) -> str:
    """
    Calculates a weighted verdict based on agent actions and their confidence scores.
    """
    action_map = {"buy": 1, "hold": 0, "sell": -1}
    tech_val = action_map.get(technical_action, 0)
    fund_val = action_map.get(fundamental_action, 0)

    # Weighted score calculation
    # The score is normalized by the sum of confidence scores to get a value between -1 and 1
    total_score = technical_score + fundamental_score
    if total_score == 0:
        return "Indeterminate" # Avoid division by zero

    weighted_score = (
        (tech_val * technical_score) + (fund_val * fundamental_score)
    ) / total_score

    # Determine final verdict based on the weighted score
    if weighted_score > 0.7:
        return "Strong Buy"
    elif weighted_score > 0.3:
        return "Buy"
    elif weighted_score > -0.3:
        return "Hold"
    elif weighted_score > -0.7:
        return "Sell"
    else:
        return "Strong Sell"

def get_reasons(technical_action: str, fundamental_action: str) -> Tuple[str, str]:
    """
    Generates descriptive reasons for the technical and fundamental actions.
    """
    tech_reason = REASON_MAPPING["technical"].get(technical_action, "No specific reason available.")
    fund_reason = REASON_MAPPING["fundamental"].get(fundamental_action, "No specific reason available.")
    return tech_reason, fund_reason
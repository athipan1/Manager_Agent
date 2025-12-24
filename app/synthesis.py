from typing import Tuple
from .config_manager import config_manager

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
    technical_score: float, # Confidence score, not used in this version but kept for API compatibility
    fundamental_action: str,
    fundamental_score: float, # Confidence score, not used in this version but kept for API compatibility
) -> str:
    """
    Calculates a weighted verdict based on agent actions and their dynamically
    configured weights.
    """
    # Fetch dynamic weights from the config manager
    agent_weights = config_manager.get("AGENT_WEIGHTS")
    tech_weight = agent_weights.get("technical", 0.5)
    fund_weight = agent_weights.get("fundamental", 0.5)

    action_map = {"buy": 1, "hold": 0, "sell": -1}
    tech_val = action_map.get(technical_action, 0)
    fund_val = action_map.get(fundamental_action, 0)

    # New weighted score calculation using dynamic weights
    weighted_score = (tech_val * tech_weight) + (fund_val * fund_weight)

    # Determine final verdict based on the weighted score.
    # Thresholds are adjusted for a direct weighted average score.
    if weighted_score >= 0.8:
        return "strong_buy"
    elif weighted_score >= 0.2:
        return "buy"
    elif weighted_score > -0.2:
        return "hold"
    elif weighted_score > -0.8:
        return "sell"
    else:
        return "strong_sell"

def get_reasons(technical_action: str, fundamental_action: str) -> Tuple[str, str]:
    """
    Generates descriptive reasons for the technical and fundamental actions.
    """
    tech_reason = REASON_MAPPING["technical"].get(technical_action, "No specific reason available.")
    fund_reason = REASON_MAPPING["fundamental"].get(fundamental_action, "No specific reason available.")
    return tech_reason, fund_reason

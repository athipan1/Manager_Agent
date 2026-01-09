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
    technical_score: float,
    fundamental_action: str,
    fundamental_score: float,
    asset_symbol: str,
) -> str:
    """
    Calculates a weighted verdict based on agent actions, their dynamically
    configured weights, and any asset-specific biases.
    """
    # Fetch dynamic weights and biases from the config manager
    agent_weights = config_manager.get("AGENT_WEIGHTS")
    asset_biases = config_manager.get("ASSET_BIASES", {})

    tech_weight = agent_weights.get("technical", 0.5)
    fund_weight = agent_weights.get("fundamental", 0.5)
    bias = asset_biases.get(asset_symbol, 0.0)

    action_map = {"buy": 1, "hold": 0, "sell": -1}
    tech_val = action_map.get(technical_action, 0)
    fund_val = action_map.get(fundamental_action, 0)

    # Calculate the base weighted score
    base_weighted_score = (tech_val * tech_weight) + (fund_val * fund_weight)

    # Apply the asset-specific bias. The bias is a multiplier.
    # A positive bias increases the magnitude of the score (pro-trend).
    # A negative bias decreases the magnitude of the score (anti-trend).
    weighted_score = base_weighted_score * (1 + bias)

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

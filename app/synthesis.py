from typing import Tuple
from .models import TechnicalAgentResponse, FundamentalAgentResponse

DECISION_MATRIX = {
    "buy": {
        "buy": "Strong Buy",
        "hold": "Accumulate",
        "sell": "Speculative Buy",
    },
    "hold": {
        "buy": "Value Buy",
        "hold": "Hold",
        "sell": "Review Fundamentals",
    },
    "sell": {
        "buy": "Contrarian Buy",
        "hold": "Wait and See",
        "sell": "Strong Sell",
    },
}

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


def get_final_verdict(technical_action: str, fundamental_action: str) -> str:
    """
    Determines the final verdict based on the decision matrix.
    """
    return DECISION_MATRIX.get(technical_action, {}).get(fundamental_action, "Indeterminate")

def get_reasons(technical_action: str, fundamental_action: str) -> Tuple[str, str]:
    """
    Generates descriptive reasons for the technical and fundamental actions.
    """
    tech_reason = REASON_MAPPING["technical"].get(technical_action, "No specific reason available.")
    fund_reason = REASON_MAPPING["fundamental"].get(fundamental_action, "No specific reason available.")
    return tech_reason, fund_reason

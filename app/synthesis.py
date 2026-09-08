from __future__ import annotations

import math
from typing import Any, Tuple

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
    },
}


def _bounded_number(value: Any, *, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(number):
        return default
    return max(low, min(high, number))


def _confidence(value: Any) -> float:
    return _bounded_number(value, default=0.0, low=0.0, high=1.0)


def _normalized_weights(raw_weights: Any) -> tuple[float, float]:
    weights = raw_weights if isinstance(raw_weights, dict) else {}
    tech_weight = _bounded_number(
        weights.get("technical", 0.5),
        default=0.5,
        low=0.0,
        high=1.0,
    )
    fund_weight = _bounded_number(
        weights.get("fundamental", 0.5),
        default=0.5,
        low=0.0,
        high=1.0,
    )
    total = tech_weight + fund_weight
    if total <= 0:
        return 0.5, 0.5
    return tech_weight / total, fund_weight / total


def get_weighted_verdict_trace(
    technical_action: str,
    technical_score: float,
    fundamental_action: str,
    fundamental_score: float,
    asset_symbol: str,
) -> dict:
    """Combine direction, confidence, configured weights and asset bias.

    Previous behavior discarded both confidence scores after accepting them as
    arguments, so a 0.51 BUY had exactly the same authority as a 0.99 BUY. The
    confidence-aware score keeps weak signals near HOLD while preserving the
    existing verdict thresholds. HOLD contributes zero directional pressure.
    """

    tech_weight, fund_weight = _normalized_weights(
        config_manager.get("AGENT_WEIGHTS")
    )
    asset_biases = config_manager.get("ASSET_BIASES", {}) or {}
    raw_bias = asset_biases.get(asset_symbol, 0.0) if isinstance(asset_biases, dict) else 0.0
    bias = _bounded_number(raw_bias, default=0.0, low=-1.0, high=1.0)

    action_map = {"buy": 1.0, "hold": 0.0, "sell": -1.0}
    tech_val = action_map.get(str(technical_action or "").lower(), 0.0)
    fund_val = action_map.get(str(fundamental_action or "").lower(), 0.0)

    base_weighted_score = (
        tech_val * _confidence(technical_score) * tech_weight
        + fund_val * _confidence(fundamental_score) * fund_weight
    )

    # Bias is allowed to amplify or damp a signal but never invert its sign.
    bias_multiplier = max(0.0, min(2.0, 1.0 + bias))
    weighted_score = base_weighted_score * bias_multiplier

    if weighted_score >= 0.8:
        verdict = "strong_buy"
    elif weighted_score >= 0.2:
        verdict = "buy"
    elif weighted_score > -0.2:
        verdict = "hold"
    elif weighted_score > -0.8:
        verdict = "sell"
    else:
        verdict = "strong_sell"
    return {
        "schema_version": "manager-verdict-trace.v1", "verdict": verdict,
        "technical": {"action": technical_action, "direction": tech_val, "weight": tech_weight,
                      "confidence": _confidence(technical_score),
                      "contribution": tech_val * _confidence(technical_score) * tech_weight},
        "fundamental": {"action": fundamental_action, "direction": fund_val, "weight": fund_weight,
                        "confidence": _confidence(fundamental_score),
                        "contribution": fund_val * _confidence(fundamental_score) * fund_weight},
        "base_weighted_score": base_weighted_score, "asset_bias": bias,
        "bias_multiplier": bias_multiplier, "directional_score": weighted_score,
        "thresholds": {"strong_buy": 0.8, "buy": 0.2, "sell": -0.2, "strong_sell": -0.8},
        "buy_passed": weighted_score >= 0.2,
        "reason_code": "DIRECTIONAL_BUY_SUPPORTED" if weighted_score >= 0.2 else "DIRECTIONAL_SCORE_BELOW_BUY_THRESHOLD",
        "final_opportunity_score_used": False, "unanimous_consensus_required": False,
        "market_regime_role": "separate_portfolio_and_execution_gate_no_directional_vote",
    }


def get_weighted_verdict(technical_action, technical_score, fundamental_action, fundamental_score, asset_symbol) -> str:
    return get_weighted_verdict_trace(
        technical_action, technical_score, fundamental_action, fundamental_score, asset_symbol,
    )["verdict"]


def get_reasons(technical_action: str, fundamental_action: str) -> Tuple[str, str]:
    """Generate descriptive reasons for technical and fundamental actions."""

    tech_reason = REASON_MAPPING["technical"].get(
        technical_action,
        "No specific reason available.",
    )
    fund_reason = REASON_MAPPING["fundamental"].get(
        fundamental_action,
        "No specific reason available.",
    )
    return tech_reason, fund_reason

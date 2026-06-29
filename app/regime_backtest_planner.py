from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List


DEFAULT_COMPARE_STRATEGIES = [
    "sma_crossover",
    "trend_following",
    "mean_reversion",
    "breakout",
]

NO_TRADE_STRATEGIES = {"no_trade", "cash", "cash_heavy"}


def _float_value(value: Any, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp_ratio(value: float) -> float:
    return max(0.0, min(value, 1.0))


def _strategy_value(strategy: Any) -> str:
    return str(strategy or "").strip()


def _allowed_strategy_names(recommendation: Dict[str, Any]) -> List[str]:
    raw_allowed = recommendation.get("allowed_strategies")
    if not raw_allowed:
        return DEFAULT_COMPARE_STRATEGIES.copy()
    allowed = [_strategy_value(strategy) for strategy in raw_allowed]
    return [strategy for strategy in allowed if strategy in DEFAULT_COMPARE_STRATEGIES]


def _ordered_strategy_names(recommended_strategy: str | None, allowed_strategies: List[str] | None = None) -> List[str]:
    if not recommended_strategy or recommended_strategy in NO_TRADE_STRATEGIES:
        return []

    allowed = allowed_strategies or DEFAULT_COMPARE_STRATEGIES
    ordered: List[str] = []
    if recommended_strategy in allowed:
        ordered.append(recommended_strategy)
    ordered.extend(strategy for strategy in allowed if strategy != recommended_strategy)
    return ordered


def build_compare_candidates(
    recommended_strategy: str | None,
    *,
    fast_window: int = 2,
    slow_window: int = 3,
    allowed_strategies: List[str] | None = None,
) -> List[Dict[str, Any]]:
    """Build Backtest_Agent candidate configs, putting the regime-selected strategy first."""
    candidates: List[Dict[str, Any]] = []
    for strategy in _ordered_strategy_names(recommended_strategy, allowed_strategies):
        candidates.append(
            {
                "name": strategy,
                "strategy": strategy,
                "fast_window": fast_window,
                "slow_window": slow_window,
            }
        )
    return candidates


def build_regime_backtest_plan(
    recommendation: Dict[str, Any],
    backtest_payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Turn a Market_Regime_Agent recommendation into a Backtest_Agent compare payload.

    This function is planning-only. It does not call Backtest_Agent or Execution_Agent.
    """
    recommended_strategy = recommendation.get("recommended_strategy")
    position_size_multiplier = _clamp_ratio(_float_value(recommendation.get("position_size_multiplier"), 1.0))
    risk_budget_multiplier = _clamp_ratio(_float_value(recommendation.get("risk_budget_multiplier"), 1.0))
    exposure_cap = _clamp_ratio(_float_value(recommendation.get("exposure_cap"), 1.0))
    effective_size_multiplier = min(position_size_multiplier, risk_budget_multiplier, exposure_cap)

    base_max_position_pct = _float_value(backtest_payload.get("max_position_pct"), 0.10)
    adjusted_max_position_pct = round(base_max_position_pct * effective_size_multiplier, 6)
    allowed_strategies = _allowed_strategy_names(recommendation)

    if (
        not recommended_strategy
        or recommended_strategy in NO_TRADE_STRATEGIES
        or adjusted_max_position_pct <= 0
        or not allowed_strategies
    ):
        return {
            "action": "no_trade",
            "reason": recommendation.get("reason") or "Market regime recommendation does not allow new entries.",
            "recommendation": recommendation,
            "market_context": {
                "position_size_multiplier": position_size_multiplier,
                "risk_budget_multiplier": risk_budget_multiplier,
                "exposure_cap": exposure_cap,
                "effective_size_multiplier": effective_size_multiplier,
                "allowed_strategies": allowed_strategies,
                "blocked_strategies": recommendation.get("blocked_strategies") or [],
                "decision_notes": recommendation.get("decision_notes") or [],
            },
            "backtest_compare_payload": None,
        }

    fast_window = int(backtest_payload.get("fast_window", 2))
    slow_window = int(backtest_payload.get("slow_window", 3))
    compare_payload = deepcopy(backtest_payload)
    compare_payload["max_position_pct"] = adjusted_max_position_pct
    compare_payload["market_context"] = {
        "position_size_multiplier": position_size_multiplier,
        "risk_budget_multiplier": risk_budget_multiplier,
        "exposure_cap": exposure_cap,
        "effective_size_multiplier": effective_size_multiplier,
        "allowed_strategies": allowed_strategies,
        "blocked_strategies": recommendation.get("blocked_strategies") or [],
        "decision_notes": recommendation.get("decision_notes") or [],
    }
    compare_payload["candidates"] = build_compare_candidates(
        recommended_strategy,
        fast_window=fast_window,
        slow_window=slow_window,
        allowed_strategies=allowed_strategies,
    )

    # Backtest compare accepts strategy candidates instead of a top-level strategy.
    compare_payload.pop("strategy", None)
    compare_payload.pop("fast_window", None)
    compare_payload.pop("slow_window", None)

    return {
        "action": "compare",
        "reason": "Built Backtest_Agent compare payload from Market_Regime_Agent strategy recommendation.",
        "recommendation": recommendation,
        "market_context": compare_payload["market_context"],
        "backtest_compare_payload": compare_payload,
    }

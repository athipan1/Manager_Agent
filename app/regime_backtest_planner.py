from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

from .market_regime_contract import evaluate_market_regime_gate
from .services.strategy_aware_sizing_service import (
    STRATEGY_AWARE_SIZING_POLICY_VERSION,
    strategy_aware_size_multiplier,
)


DEFAULT_COMPARE_STRATEGIES = [
    "sma_crossover",
    "trend_following",
    "mean_reversion",
    "breakout",
]

NO_TRADE_STRATEGIES = {"no_trade", "cash", "cash_heavy"}
DEFAULT_MIN_STRATEGY_AFFINITY = 0.60


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
    return str(strategy or "").strip().lower()


def _allowed_strategy_names(recommendation: Dict[str, Any]) -> List[str]:
    raw_allowed = recommendation.get("allowed_strategies")
    if raw_allowed is None:
        return DEFAULT_COMPARE_STRATEGIES.copy()
    allowed = [_strategy_value(strategy) for strategy in raw_allowed]
    return [strategy for strategy in allowed if strategy in DEFAULT_COMPARE_STRATEGIES]


def _opportunity_strategy_names(
    opportunity_profile: Dict[str, Any] | None,
    *,
    min_affinity: float = DEFAULT_MIN_STRATEGY_AFFINITY,
) -> List[str] | None:
    """Return opportunity-compatible strategy families, or None when absent.

    Scanner evidence is advisory. Manager owns the intersection and never lets a
    Scanner hint expand Market_Regime_Agent's allow-list.
    """

    if not opportunity_profile:
        return None
    if _strategy_value(opportunity_profile.get("status")) != "qualified":
        return []

    affinity = opportunity_profile.get("strategy_affinity")
    affinity = affinity if isinstance(affinity, dict) else {}
    selected: List[str] = []
    for strategy in DEFAULT_COMPARE_STRATEGIES:
        if strategy == "sma_crossover":
            # Scanner v1 does not emit a separate SMA affinity. It remains usable
            # only when no opportunity profile is supplied.
            continue
        try:
            score = float(affinity.get(strategy))
        except (TypeError, ValueError):
            continue
        if 0.0 <= score <= 1.0 and score >= min_affinity:
            selected.append(strategy)

    if selected:
        return selected

    preferred = _strategy_value(opportunity_profile.get("preferred_strategy_hint"))
    if preferred in DEFAULT_COMPARE_STRATEGIES and preferred != "sma_crossover" and not affinity:
        return [preferred]
    return []


def _ordered_strategy_names(recommended_strategy: str | None) -> List[str]:
    recommended = _strategy_value(recommended_strategy)
    if not recommended or recommended in NO_TRADE_STRATEGIES:
        return []

    ordered: List[str] = []
    if recommended in DEFAULT_COMPARE_STRATEGIES:
        ordered.append(recommended)
    ordered.extend(
        strategy for strategy in DEFAULT_COMPARE_STRATEGIES if strategy != recommended
    )
    return ordered


def build_compare_candidates(
    recommended_strategy: str | None,
    *,
    fast_window: int = 2,
    slow_window: int = 3,
    allowed_strategies: List[str] | None = None,
) -> List[Dict[str, Any]]:
    """Build Backtest candidates without testing strategies denied by current policy."""

    allowed = None if allowed_strategies is None else set(allowed_strategies)
    candidates: List[Dict[str, Any]] = []
    for strategy in _ordered_strategy_names(recommended_strategy):
        if allowed is not None and strategy not in allowed:
            continue
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
    *,
    market_gate: Dict[str, Any] | None = None,
    opportunity_profile: Dict[str, Any] | None = None,
    min_strategy_affinity: float = DEFAULT_MIN_STRATEGY_AFFINITY,
) -> Dict[str, Any]:
    """Build a policy-constrained Backtest compare plan.

    Market_Regime_Agent owns the strategy allow-list. Optional Scanner opportunity
    evidence can only narrow that list; it can never add a strategy that Market
    Regime disallowed. Strategy-aware Scanner qualification may additionally reduce
    size, but never increases the Market Regime or Risk budget.
    """

    gate = market_gate or evaluate_market_regime_gate({}, recommendation)
    recommended_strategy = _strategy_value(recommendation.get("recommended_strategy"))
    position_size_multiplier = _clamp_ratio(
        _float_value(recommendation.get("position_size_multiplier"), 1.0)
    )
    risk_budget_multiplier = _clamp_ratio(
        _float_value(recommendation.get("risk_budget_multiplier"), 1.0)
    )
    exposure_cap = _clamp_ratio(
        _float_value(recommendation.get("exposure_cap"), 1.0)
    )
    scanner_opportunity_size_multiplier = strategy_aware_size_multiplier(
        opportunity_profile
    )
    effective_size_multiplier = min(
        position_size_multiplier,
        risk_budget_multiplier,
        exposure_cap,
        scanner_opportunity_size_multiplier,
    )

    base_max_position_pct = _float_value(backtest_payload.get("max_position_pct"), 0.10)
    adjusted_max_position_pct = round(
        base_max_position_pct * effective_size_multiplier,
        6,
    )
    regime_allowed_strategies = _allowed_strategy_names(recommendation)
    opportunity_allowed_strategies = _opportunity_strategy_names(
        opportunity_profile,
        min_affinity=max(0.0, min(1.0, float(min_strategy_affinity))),
    )
    if opportunity_allowed_strategies is None:
        compatible_strategies = regime_allowed_strategies.copy()
    else:
        opportunity_set = set(opportunity_allowed_strategies)
        compatible_strategies = [
            strategy
            for strategy in regime_allowed_strategies
            if strategy in opportunity_set
        ]

    preferred_hint = _strategy_value(
        (opportunity_profile or {}).get("preferred_strategy_hint")
    )
    if recommended_strategy in compatible_strategies:
        effective_recommended_strategy = recommended_strategy
    elif preferred_hint in compatible_strategies:
        effective_recommended_strategy = preferred_hint
    elif compatible_strategies:
        effective_recommended_strategy = compatible_strategies[0]
    else:
        effective_recommended_strategy = ""

    market_context = {
        "position_size_multiplier": position_size_multiplier,
        "risk_budget_multiplier": risk_budget_multiplier,
        "exposure_cap": exposure_cap,
        "scanner_opportunity_size_multiplier": scanner_opportunity_size_multiplier,
        "scanner_opportunity_sizing_policy_version": STRATEGY_AWARE_SIZING_POLICY_VERSION,
        "effective_size_multiplier": effective_size_multiplier,
        "allowed_strategies": compatible_strategies,
        "market_regime_allowed_strategies": regime_allowed_strategies,
        "scanner_opportunity_allowed_strategies": opportunity_allowed_strategies,
        "scanner_preferred_strategy_hint": preferred_hint or None,
        "strategy_affinity_threshold": (
            max(0.0, min(1.0, float(min_strategy_affinity)))
            if opportunity_profile
            else None
        ),
        "effective_recommended_strategy": effective_recommended_strategy or None,
        "blocked_strategies": recommendation.get("blocked_strategies") or [],
        "decision_notes": recommendation.get("decision_notes") or [],
        "market_regime_gate": gate,
    }

    no_trade_reason = None
    if opportunity_profile and not compatible_strategies and regime_allowed_strategies:
        no_trade_reason = (
            "Scanner opportunity strategy affinity has no intersection with the "
            "Market_Regime_Agent allow-list."
        )

    if (
        gate.get("new_entries_allowed") is not True
        or not recommended_strategy
        or recommended_strategy in NO_TRADE_STRATEGIES
        or adjusted_max_position_pct <= 0
        or not compatible_strategies
        or not effective_recommended_strategy
    ):
        gate_reasons = gate.get("reasons") or []
        reason = (
            no_trade_reason
            or (
                "; ".join(str(item) for item in gate_reasons)
                if gate_reasons
                else recommendation.get("reason")
                or "Market regime recommendation does not allow new entries."
            )
        )
        return {
            "action": "no_trade",
            "reason": reason,
            "recommendation": recommendation,
            "market_context": market_context,
            "backtest_compare_payload": None,
        }

    fast_window = int(backtest_payload.get("fast_window", 2))
    slow_window = int(backtest_payload.get("slow_window", 3))
    compare_payload = deepcopy(backtest_payload)
    compare_payload["max_position_pct"] = adjusted_max_position_pct
    compare_payload["market_context"] = market_context
    compare_payload["candidates"] = build_compare_candidates(
        effective_recommended_strategy,
        fast_window=fast_window,
        slow_window=slow_window,
        allowed_strategies=compatible_strategies,
    )

    compare_payload.pop("strategy", None)
    compare_payload.pop("fast_window", None)
    compare_payload.pop("slow_window", None)

    return {
        "action": "compare",
        "reason": (
            "Built Backtest_Agent compare payload from the intersection of "
            "Market_Regime_Agent authority and Scanner opportunity evidence."
            if opportunity_profile
            else "Built Backtest_Agent compare payload from Market_Regime_Agent strategy recommendation."
        ),
        "recommendation": recommendation,
        "market_context": compare_payload["market_context"],
        "backtest_compare_payload": compare_payload,
    }

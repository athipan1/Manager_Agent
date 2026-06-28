from __future__ import annotations

from typing import Any, Dict

from .alpha_agent_client import recommend_market_strategy
from .backtest_agent_client import BacktestAgentClient
from .regime_backtest_planner import build_regime_backtest_plan


async def run_regime_backtest_compare(
    payload: Dict[str, Any],
    correlation_id: str,
) -> Dict[str, Any]:
    """Build and execute a Backtest_Agent compare request from market-regime guidance.

    This is validation-only. It calls Backtest_Agent but never calls Execution_Agent
    and never places orders.
    """
    market_regime_payload = payload.get("market_regime") or {}
    backtest_payload = payload.get("backtest") or {}

    strategy_data = await recommend_market_strategy(market_regime_payload, correlation_id)
    recommendation = strategy_data.get("recommendation") or {}
    plan = build_regime_backtest_plan(recommendation, backtest_payload)

    if plan.get("action") != "compare":
        return {
            "enabled": strategy_data.get("enabled", True),
            "market_strategy": strategy_data,
            "plan": plan,
            "backtest_compare": None,
            "executed": False,
            "execution_reason": "no compare request was created by the regime backtest plan",
        }

    compare_payload = plan.get("backtest_compare_payload") or {}
    async with BacktestAgentClient() as client:
        backtest_compare = await client.compare_strategies(compare_payload, correlation_id)

    return {
        "enabled": strategy_data.get("enabled", True),
        "market_strategy": strategy_data,
        "plan": plan,
        "backtest_compare": backtest_compare,
        "executed": True,
        "execution_reason": "Backtest_Agent /backtest/compare completed successfully.",
    }

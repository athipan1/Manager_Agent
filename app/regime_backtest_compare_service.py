from __future__ import annotations

from typing import Any, Dict

from .backtest_agent_client import BacktestAgentClient
from .regime_backtest_planner import build_regime_backtest_plan


async def run_regime_backtest_compare(
    *,
    market_strategy: Dict[str, Any],
    backtest_payload: Dict[str, Any],
    correlation_id: str,
    backtest_client: BacktestAgentClient | None = None,
) -> Dict[str, Any]:
    """Build and execute a Backtest_Agent compare request from regime guidance.

    This remains advisory/simulation-only. It does not call Execution_Agent.
    """
    recommendation = market_strategy.get("recommendation") or {}
    plan = build_regime_backtest_plan(recommendation, backtest_payload)

    if plan.get("action") != "compare":
        return {
            "action": plan.get("action", "no_trade"),
            "market_strategy": market_strategy,
            "plan": plan,
            "compare_result": None,
        }

    compare_payload = plan.get("backtest_compare_payload") or {}
    client = backtest_client or BacktestAgentClient()
    if backtest_client is not None:
        compare_result = await client.compare_strategies(compare_payload, correlation_id)
    else:
        async with client as managed_client:
            compare_result = await managed_client.compare_strategies(compare_payload, correlation_id)

    return {
        "action": "compare",
        "market_strategy": market_strategy,
        "plan": plan,
        "compare_result": compare_result,
    }

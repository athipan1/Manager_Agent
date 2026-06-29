from __future__ import annotations

from typing import Any, Dict

from .alpha_agent_client import recommend_market_strategy
from .backtest_agent_client import BacktestAgentClient
from .regime_backtest_planner import build_regime_backtest_plan


APPROVED_DECISION = "candidate_approved"
REVIEW_DECISION = "needs_review"
NO_TRADE_DECISION = "no_trade"


def _strategy_from_result(result: Dict[str, Any] | None) -> str | None:
    if not result:
        return None
    strategy = result.get("strategy")
    if strategy:
        return strategy
    candidate = result.get("candidate") or {}
    return candidate.get("strategy")


def build_regime_backtest_decision(compare_result: Dict[str, Any]) -> Dict[str, Any]:
    plan = compare_result.get("plan") or {}
    recommendation = plan.get("recommendation") or {}
    recommended_strategy = recommendation.get("recommended_strategy")

    if compare_result.get("executed") is not True or plan.get("action") != "compare":
        return {
            "decision": NO_TRADE_DECISION,
            "confidence": "low",
            "recommended_strategy": recommended_strategy,
            "backtest_best_strategy": None,
            "reason": plan.get("reason") or compare_result.get("execution_reason") or "No backtest comparison was run.",
        }

    backtest_compare = compare_result.get("backtest_compare") or {}
    best_strategy = _strategy_from_result(backtest_compare.get("best"))
    ranked_results = backtest_compare.get("ranked_results") or []
    ranked_strategies = [_strategy_from_result(item) for item in ranked_results]
    ranked_strategies = [strategy for strategy in ranked_strategies if strategy]

    if recommended_strategy and best_strategy == recommended_strategy:
        return {
            "decision": APPROVED_DECISION,
            "confidence": "high",
            "recommended_strategy": recommended_strategy,
            "backtest_best_strategy": best_strategy,
            "reason": "Market regime recommendation matches the best Backtest_Agent compare result.",
        }

    if recommended_strategy and recommended_strategy in ranked_strategies:
        return {
            "decision": REVIEW_DECISION,
            "confidence": "medium",
            "recommended_strategy": recommended_strategy,
            "backtest_best_strategy": best_strategy,
            "reason": "Market regime recommendation was tested but did not rank first.",
        }

    return {
        "decision": REVIEW_DECISION,
        "confidence": "low",
        "recommended_strategy": recommended_strategy,
        "backtest_best_strategy": best_strategy,
        "reason": "Backtest compare results did not validate the market-regime recommendation.",
    }


async def run_regime_backtest_compare(
    payload: Dict[str, Any],
    correlation_id: str,
) -> Dict[str, Any]:
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


async def run_regime_backtest_decision(
    payload: Dict[str, Any],
    correlation_id: str,
) -> Dict[str, Any]:
    compare_result = await run_regime_backtest_compare(payload, correlation_id)
    decision = build_regime_backtest_decision(compare_result)
    return {
        **compare_result,
        "decision": decision,
    }

from __future__ import annotations

import datetime
import uuid
from typing import Any, Dict

from fastapi import APIRouter

from ..alpha_agent_client import build_alpha_advisory, check_alpha_health, recommend_market_strategy
from ..contracts import StandardAgentResponse
from ..regime_backtest_planner import build_regime_backtest_plan
from ..workflows.single_analysis_workflow import manager_metadata


router = APIRouter(prefix="/alpha", tags=["alpha-agents"])


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


def _metadata(correlation_id: str) -> Dict[str, Any]:
    metadata = manager_metadata()
    metadata["correlation_id"] = correlation_id
    metadata["alpha_advisory_only"] = True
    return metadata


@router.get("/health", response_model=StandardAgentResponse)
async def alpha_health() -> StandardAgentResponse:
    correlation_id = str(uuid.uuid4())
    data = await check_alpha_health(correlation_id)
    unhealthy = [
        name
        for name, service in data.get("services", {}).items()
        if service.get("status") == "unhealthy"
    ]
    return StandardAgentResponse(
        status="error" if unhealthy else "success",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=utc_now(),
        data=data,
        metadata=_metadata(correlation_id),
        error={"unhealthy_services": unhealthy} if unhealthy else None,
    )


@router.post("/advisory", response_model=StandardAgentResponse)
async def alpha_advisory(payload: Dict[str, Any]) -> StandardAgentResponse:
    """Aggregate advisory responses from the four alpha-layer agents.

    Expected optional payload keys:
    - market_regime: forwarded to Market_Regime_Agent /market/regime
    - portfolio: forwarded to Portfolio_Agent /portfolio/exposure
    - profit: forwarded to Profit_Agent /profit/plan
    - performance: forwarded to Performance_Agent /performance/report
    """
    correlation_id = str(uuid.uuid4())
    data = await build_alpha_advisory(payload, correlation_id)
    return StandardAgentResponse(
        status="error" if data.get("errors") else "success",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=utc_now(),
        data=data,
        metadata=_metadata(correlation_id),
        error=data.get("errors") or None,
    )


@router.post("/market-strategy", response_model=StandardAgentResponse)
async def alpha_market_strategy(payload: Dict[str, Any]) -> StandardAgentResponse:
    """Ask Market_Regime_Agent which Backtest_Agent strategy should be favored."""
    correlation_id = str(uuid.uuid4())
    try:
        data = await recommend_market_strategy(payload, correlation_id)
        return StandardAgentResponse(
            status="success",
            agent_type="manager-agent",
            version="1.0.0",
            timestamp=utc_now(),
            data=data,
            metadata=_metadata(correlation_id),
            error=None,
        )
    except Exception as exc:
        return StandardAgentResponse(
            status="error",
            agent_type="manager-agent",
            version="1.0.0",
            timestamp=utc_now(),
            data={"enabled": True, "recommendation": None},
            metadata=_metadata(correlation_id),
            error={"market_strategy": str(exc)},
        )


@router.post("/regime-backtest-plan", response_model=StandardAgentResponse)
async def alpha_regime_backtest_plan(payload: Dict[str, Any]) -> StandardAgentResponse:
    """Build a Backtest_Agent compare payload from a Market_Regime_Agent strategy recommendation.

    Expected payload:
    - market_regime: request forwarded to Market_Regime_Agent /market/strategy
    - backtest: base Backtest_Agent compare payload fields such as symbols, bars, equity, risk settings
    """
    correlation_id = str(uuid.uuid4())
    try:
        market_regime_payload = payload.get("market_regime") or {}
        backtest_payload = payload.get("backtest") or {}
        strategy_data = await recommend_market_strategy(market_regime_payload, correlation_id)
        recommendation = strategy_data.get("recommendation") or {}
        plan = build_regime_backtest_plan(recommendation, backtest_payload)
        data = {
            "enabled": strategy_data.get("enabled", True),
            "market_strategy": strategy_data,
            "plan": plan,
        }
        return StandardAgentResponse(
            status="success",
            agent_type="manager-agent",
            version="1.0.0",
            timestamp=utc_now(),
            data=data,
            metadata=_metadata(correlation_id),
            error=None,
        )
    except Exception as exc:
        return StandardAgentResponse(
            status="error",
            agent_type="manager-agent",
            version="1.0.0",
            timestamp=utc_now(),
            data={"enabled": True, "market_strategy": None, "plan": None},
            metadata=_metadata(correlation_id),
            error={"regime_backtest_plan": str(exc)},
        )

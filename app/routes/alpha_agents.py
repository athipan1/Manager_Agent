from __future__ import annotations

import datetime
import uuid
from typing import Any, Dict

from fastapi import APIRouter

from ..alpha_agent_client import build_alpha_advisory, check_alpha_health
from ..contracts import StandardAgentResponse
from ..workflows.single_analysis_workflow import manager_metadata


router = APIRouter(prefix="/alpha", tags=["alpha-agents"])


def utc_now() -> datetime.datetime:
    return datetime.datetime.now(datetime.UTC)


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
        metadata=manager_metadata(correlation_id=correlation_id),
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
        metadata=manager_metadata(correlation_id=correlation_id),
        error=data.get("errors") or None,
    )

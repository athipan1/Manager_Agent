"""Discovery routes for Manager_Agent."""

from __future__ import annotations

from fastapi import APIRouter

from ..contracts import StandardAgentResponse
from ..models import DiscoverAnalyzeTradeRequest
from ..workflows.gated_guarded_discovery_workflow import (
    run_gated_guarded_discover_analyze_trade_flow
    as run_discover_analyze_trade_flow,
)

router = APIRouter()


@router.post(
    "/discover-analyze-trade",
    response_model=StandardAgentResponse,
)
async def discover_analyze_trade_endpoint(
    request: DiscoverAnalyzeTradeRequest,
):
    """Discover, gate exposure, risk-check and optionally execute trades."""
    return await run_discover_analyze_trade_flow(request)

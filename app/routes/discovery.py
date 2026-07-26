"""Discovery routes for Manager_Agent."""

from __future__ import annotations

from fastapi import APIRouter

from ..contracts import StandardAgentResponse
from ..models import DiscoverAnalyzeTradeRequest
from ..workflows.gated_guarded_discovery_workflow import (
    run_gated_guarded_discover_analyze_trade_flow
    as run_discover_analyze_trade_flow,
)
from ..workflows.scanner_preselection_workflow import (
    run_scanner_preselection_flow,
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


@router.post(
    "/scanner-preselection",
    response_model=StandardAgentResponse,
)
async def scanner_preselection_endpoint(
    request: DiscoverAnalyzeTradeRequest,
):
    """Run read-only hourly discovery without an Execution_Agent dependency."""
    return await run_scanner_preselection_flow(request)

"""Discovery routes for Manager_Agent."""

from __future__ import annotations

from fastapi import APIRouter

from ..contracts import StandardAgentResponse
from ..models import DiscoverAnalyzeTradeRequest
from ..workflows.discovery_workflow import run_discover_analyze_trade_flow

router = APIRouter()


@router.post("/discover-analyze-trade", response_model=StandardAgentResponse)
async def discover_analyze_trade_endpoint(request: DiscoverAnalyzeTradeRequest):
    """Discover, analyze, allocate, risk-check, and optionally execute trades."""
    return await run_discover_analyze_trade_flow(request)

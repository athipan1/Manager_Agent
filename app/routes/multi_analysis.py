"""Multi-analysis routes for Manager_Agent."""

from __future__ import annotations

from fastapi import APIRouter

from ..contracts import StandardAgentResponse
from ..models import MultiAgentRequestBody
from ..workflows.multi_analysis_workflow import run_multi_analysis_flow

router = APIRouter()


@router.post("/analyze-multi", response_model=StandardAgentResponse)
async def analyze_tickers_endpoint(request: MultiAgentRequestBody):
    """Analyze multiple tickers and orchestrate portfolio-level risk/execution."""
    return await run_multi_analysis_flow(request)

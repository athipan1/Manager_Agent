"""Scanner-backed routes for Manager_Agent."""

from __future__ import annotations

from fastapi import APIRouter

from ..contracts import StandardAgentResponse
from ..models import ScanAndAnalyzeRequest
from ..workflows.scan_analysis_workflow import run_scan_and_analyze_flow

router = APIRouter()


@router.post("/scan-and-analyze", response_model=StandardAgentResponse)
async def scan_and_analyze_endpoint(request: ScanAndAnalyzeRequest):
    """Scan candidates and delegate selected symbols to multi-analysis."""
    return await run_scan_and_analyze_flow(request)

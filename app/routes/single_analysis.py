"""Single-symbol analysis routes for Manager_Agent.

This router is ready to replace the legacy route functions in `app.main` once
`main.py` includes it with `app.include_router(router)`. Keeping it separate
first makes the migration reviewable and easy to test.
"""

from __future__ import annotations

from fastapi import APIRouter

from ..contracts import StandardAgentResponse
from ..models import AgentRequestBody
from ..workflows.single_analysis_workflow import run_single_analysis_flow

router = APIRouter()


@router.post("/analyze", response_model=StandardAgentResponse)
async def analyze_ticker(request: AgentRequestBody):
    """Analyze a single ticker and execute when eligible."""
    return await run_single_analysis_flow(request, dry_run=False)


@router.post("/dry-run/analyze", response_model=StandardAgentResponse)
async def dry_run_analyze_ticker(request: AgentRequestBody):
    """Analyze a single ticker without submitting execution."""
    return await run_single_analysis_flow(request, dry_run=True)

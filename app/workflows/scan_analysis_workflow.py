"""Scan-and-analyze workflow for Manager_Agent.

This module is the route-ready orchestration layer for `/scan-and-analyze`.
It scans candidates through Scanner_Agent, selects symbols, then delegates to
the multi-analysis workflow.
"""

from __future__ import annotations

import uuid
from typing import Any, List, Optional, Union

from fastapi import HTTPException

from ..config_manager import config_manager
from ..contracts import ScannerCandidate, ScannerResponseData, StandardAgentResponse
from ..logger import report_logger
from ..models import (
    ExecutionSummary,
    MultiAgentRequestBody,
    MultiOrchestratorResponse,
    ScanAndAnalyzeRequest,
)
from ..resilient_client import AgentUnavailable
from ..scanner_client import ScannerAgentClient
from ..stock_guard import StockGuardError
from .multi_analysis_workflow import run_multi_analysis_flow
from .single_analysis_workflow import manager_metadata, utc_now


def scanner_candidates_from_response_data(data: Any) -> List[Any]:
    """Normalize scanner response data into a candidate list."""
    if isinstance(data, ScannerResponseData):
        return list(data.candidates)
    if isinstance(data, dict):
        return list(data.get("candidates", []))
    if hasattr(data, "model_dump"):
        payload = data.model_dump(mode="json")
        return list(payload.get("candidates", [])) if isinstance(payload, dict) else []
    return []


def scanner_candidate_recommendation(candidate: Any) -> Optional[str]:
    """Return a candidate recommendation value, if present."""
    if isinstance(candidate, ScannerCandidate):
        return candidate.recommendation
    if isinstance(candidate, dict):
        return candidate.get("recommendation")
    return getattr(candidate, "recommendation", None)


def scanner_candidate_symbol(candidate: Any) -> Optional[str]:
    """Return a candidate symbol value, if present."""
    if isinstance(candidate, ScannerCandidate):
        return candidate.symbol
    if isinstance(candidate, dict):
        return candidate.get("symbol")
    return getattr(candidate, "symbol", None)


def sort_technical_candidates(candidates: List[Any]) -> List[Any]:
    """Sort technical candidates with STRONG_BUY first, preserving legacy behavior."""
    return sorted(
        candidates,
        key=lambda candidate: 2 if scanner_candidate_recommendation(candidate) == "STRONG_BUY" else 1,
        reverse=True,
    )


def selected_scan_tickers(candidates: List[Any], max_candidates: int) -> List[str]:
    """Return non-empty candidate symbols capped by max_candidates."""
    return [symbol for symbol in [scanner_candidate_symbol(candidate) for candidate in candidates[:max_candidates]] if symbol]


def empty_scan_response(correlation_id: str) -> StandardAgentResponse:
    """Build the legacy-compatible empty scanner result response."""
    multi_report = MultiOrchestratorResponse(
        multi_report_id=correlation_id,
        timestamp=utc_now(),
        execution_summary=ExecutionSummary(
            total_trades_approved=0,
            total_trades_executed=0,
            total_trades_failed=0,
        ),
        results=[],
    )
    return StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=utc_now(),
        data=multi_report,
        metadata=manager_metadata(),
    )


async def scan_candidates(request: ScanAndAnalyzeRequest, correlation_id: str) -> List[Any]:
    """Scan Scanner_Agent candidates for the requested scan type."""
    async with ScannerAgentClient() as scanner_client:
        if request.scan_type == "technical":
            scan_response = await scanner_client.scan(request.symbols, correlation_id)
        else:
            scan_response = await scanner_client.scan_fundamental(request.symbols, correlation_id)

    candidates = scanner_candidates_from_response_data(scan_response.data)
    if request.scan_type == "technical":
        candidates = sort_technical_candidates(candidates)
    return candidates


async def run_scan_and_analyze_flow(request: ScanAndAnalyzeRequest) -> StandardAgentResponse:
    """Run scanner selection and delegate selected symbols to multi-analysis."""
    correlation_id = str(uuid.uuid4())
    account_id: Union[int, str] = request.account_id if request.account_id is not None else config_manager.get("DEFAULT_ACCOUNT_ID")

    try:
        candidates = await scan_candidates(request, correlation_id)
        selected_tickers = selected_scan_tickers(candidates, request.max_candidates)
        if not selected_tickers:
            return empty_scan_response(correlation_id)

        return await run_multi_analysis_flow(
            MultiAgentRequestBody(
                tickers=selected_tickers,
                period="1mo",
                account_id=account_id,
            )
        )
    except StockGuardError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AgentUnavailable as exc:
        report_logger.critical(f"Scanner Agent is unavailable: {exc}")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        report_logger.exception(f"Scan and analyze failed: {exc}, correlation_id={correlation_id}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

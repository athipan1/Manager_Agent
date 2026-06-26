"""Guarded discovery workflow entrypoint.

This module wraps the existing discovery workflow with a preflight safety gate.
If Database_Agent reports that Broker and Database context are not safely synced,
it forces the downstream discovery flow into analysis-only mode and returns a
blocked execution result instead of allowing new entries to reach Risk/Execution.
"""

from __future__ import annotations

from typing import Any, Dict

from ..contracts import StandardAgentResponse
from ..database_client import DatabaseAgentClient
from ..logger import report_logger
from ..models import DiscoverAnalyzeTradeRequest
from ..services.database_sync_gate import (
    database_sync_allows_automation,
    database_sync_blocked_execution,
    database_sync_summary,
)
from .discovery_workflow import run_discover_analyze_trade_flow as run_unguarded_discover_analyze_trade_flow
from .single_analysis_workflow import manager_metadata, utc_now


def _request_with_execution_disabled(request: DiscoverAnalyzeTradeRequest) -> DiscoverAnalyzeTradeRequest:
    if hasattr(request, "model_copy"):
        return request.model_copy(update={"execute": False})
    data = request.dict()
    data["execute"] = False
    return DiscoverAnalyzeTradeRequest(**data)


async def load_database_sync_status(account_id: Any, correlation_id: str) -> Dict[str, Any]:
    try:
        async with DatabaseAgentClient() as db_client:
            getter = getattr(db_client, "get_broker_sync_status", None)
            if getter is None:
                return {}
            return await getter(account_id, correlation_id)
    except Exception as exc:
        report_logger.warning(
            f"Database sync gate status lookup failed for account {account_id}: {exc}, correlation_id={correlation_id}"
        )
        return {
            "mismatch": {
                "is_synced": False,
                "summary": {
                    "status": "unavailable",
                    "severity": "warning",
                    "recommended_action": "check_database_sync_status",
                },
                "diagnostics": {"error": str(exc)},
            }
        }


def _with_blocked_execution(response: StandardAgentResponse, database_sync: Dict[str, Any]) -> StandardAgentResponse:
    data = response.data if isinstance(response.data, dict) else {}
    if not data:
        return response

    execution = database_sync_blocked_execution(database_sync)
    data["database_sync"] = database_sync
    data["execution"] = execution
    data["risk_approvals"] = []
    data["execution_candidates"] = []

    portfolio_summary = data.get("portfolio_summary")
    if isinstance(portfolio_summary, dict):
        portfolio_summary["approved_positions"] = 0
        portfolio_summary["rejected_positions"] = 0
        portfolio_summary["execution_status"] = execution["status"]
        portfolio_summary["database_sync_status"] = database_sync_summary(database_sync).get("status")

    legacy = data.get("legacy")
    if isinstance(legacy, dict):
        legacy["trade_decision"] = None
        legacy["risk_approval_id"] = None

    return StandardAgentResponse(
        status=response.status,
        agent_type=response.agent_type,
        version=response.version,
        timestamp=response.timestamp,
        data=data,
        metadata=response.metadata,
        error=response.error,
    )


async def run_guarded_discover_analyze_trade_flow(request: DiscoverAnalyzeTradeRequest) -> StandardAgentResponse:
    """Run discovery while blocking new entries when DB/Broker sync is unsafe."""
    correlation_id = "database-sync-gate"
    account_id = request.account_id if request.account_id is not None else None
    database_sync = await load_database_sync_status(account_id or 1, correlation_id)

    if request.execute and not database_sync_allows_automation(database_sync):
        analysis_only_request = _request_with_execution_disabled(request)
        response = await run_unguarded_discover_analyze_trade_flow(analysis_only_request)
        return _with_blocked_execution(response, database_sync)

    response = await run_unguarded_discover_analyze_trade_flow(request)
    if isinstance(response.data, dict) and database_sync:
        response.data.setdefault("database_sync", database_sync)
        portfolio_summary = response.data.get("portfolio_summary")
        if isinstance(portfolio_summary, dict):
            portfolio_summary.setdefault("database_sync_status", database_sync_summary(database_sync).get("status"))
    return response

"""Guarded discovery workflow entrypoint.

This module wraps the existing discovery workflow with a preflight safety gate.
Before the gate runs, it tries to capture the latest broker state into
Database_Agent so a missing snapshot can become a fresh sync result.
"""

from __future__ import annotations

from typing import Any, Dict

from ..contracts import StandardAgentResponse
from ..database_client import DatabaseAgentClient
from ..execution_client import ExecutionAgentClient
from ..logger import report_logger
from ..models import DiscoverAnalyzeTradeRequest
from ..services.database_sync_gate import (
    database_sync_allows_automation,
    database_sync_blocked_execution,
    database_sync_summary,
)
from .discovery_workflow import run_discover_analyze_trade_flow as run_unguarded_discover_analyze_trade_flow


def _request_with_execution_disabled(request: DiscoverAnalyzeTradeRequest) -> DiscoverAnalyzeTradeRequest:
    if hasattr(request, "model_copy"):
        return request.model_copy(update={"execute": False})
    data = request.dict()
    data["execute"] = False
    return DiscoverAnalyzeTradeRequest(**data)


def _standard_response_data(response: Any) -> Dict[str, Any]:
    payload = response.data if hasattr(response, "data") else response
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json")
    return payload if isinstance(payload, dict) else {}


def _broker_state_from_execution_response(response: Any, account_id: Any) -> Dict[str, Any]:
    payload = _standard_response_data(response)
    state = payload.get("broker_state") or payload.get("state") or payload
    if not isinstance(state, dict):
        return {}
    broker_account = state.get("account") or {}
    return {
        "source": "manager_preflight",
        "account_id": account_id,
        "broker": state.get("broker") or broker_account.get("broker"),
        "paper": state.get("paper") if "paper" in state else broker_account.get("paper"),
        "captured_at": state.get("captured_at") or state.get("timestamp"),
        "account": broker_account,
        "positions": state.get("positions") or [],
        "open_orders": state.get("open_orders") or state.get("orders") or [],
        "summary": state.get("summary") or {
            "position_count": len(state.get("positions") or []),
            "open_order_count": len(state.get("open_orders") or state.get("orders") or []),
        },
    }


async def capture_broker_snapshot(account_id: Any, correlation_id: str) -> Dict[str, Any]:
    """Fetch current broker state from Execution_Agent and persist it to Database_Agent."""
    try:
        async with ExecutionAgentClient() as exec_client:
            execution_response = await exec_client.broker_state(account_id, correlation_id)
        broker_state = _broker_state_from_execution_response(execution_response, account_id)
        if not broker_state.get("account"):
            return {"status": "skipped", "reason": "broker_state_missing_account"}
        async with DatabaseAgentClient() as db_client:
            result = await db_client.capture_broker_snapshot(broker_state, correlation_id)
        return {"status": "captured", "result": result, "broker_state_summary": broker_state.get("summary") or {}}
    except Exception as exc:
        report_logger.warning(
            f"Broker snapshot capture failed for account {account_id}: {exc}, correlation_id={correlation_id}"
        )
        return {"status": "failed", "error": str(exc)}


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


def _with_blocked_execution(response: StandardAgentResponse, database_sync: Dict[str, Any], snapshot_capture: Dict[str, Any]) -> StandardAgentResponse:
    data = response.data if isinstance(response.data, dict) else {}
    if not data:
        return response

    execution = database_sync_blocked_execution(database_sync)
    data["database_sync"] = database_sync
    data["broker_snapshot_capture"] = snapshot_capture
    data["execution"] = execution
    data["risk_approvals"] = []
    data["execution_candidates"] = []

    portfolio_summary = data.get("portfolio_summary")
    if isinstance(portfolio_summary, dict):
        portfolio_summary["approved_positions"] = 0
        portfolio_summary["rejected_positions"] = 0
        portfolio_summary["execution_status"] = execution["status"]
        portfolio_summary["database_sync_status"] = database_sync_summary(database_sync).get("status")
        portfolio_summary["broker_snapshot_capture_status"] = snapshot_capture.get("status")

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
    account_id = request.account_id if request.account_id is not None else 1
    snapshot_capture = await capture_broker_snapshot(account_id, correlation_id) if request.execute else {"status": "skipped", "reason": "request.execute=false"}
    database_sync = await load_database_sync_status(account_id, correlation_id)

    if request.execute and not database_sync_allows_automation(database_sync):
        analysis_only_request = _request_with_execution_disabled(request)
        response = await run_unguarded_discover_analyze_trade_flow(analysis_only_request)
        return _with_blocked_execution(response, database_sync, snapshot_capture)

    response = await run_unguarded_discover_analyze_trade_flow(request)
    if isinstance(response.data, dict):
        if database_sync:
            response.data.setdefault("database_sync", database_sync)
        response.data.setdefault("broker_snapshot_capture", snapshot_capture)
        portfolio_summary = response.data.get("portfolio_summary")
        if isinstance(portfolio_summary, dict):
            portfolio_summary.setdefault("database_sync_status", database_sync_summary(database_sync).get("status"))
            portfolio_summary.setdefault("broker_snapshot_capture_status", snapshot_capture.get("status"))
    return response

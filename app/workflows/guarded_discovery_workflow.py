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


VALID_STRATEGY_BUCKETS = {"core_dividend", "value_rebound", "news_momentum"}


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


def _unwrap_possible_standard_response_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Return the useful broker payload even when it is nested under `data`.

    Some Execution_Agent endpoints return `{status, data: {...}}` before the
    Manager client converts it into a StandardAgentResponse. Keeping this helper
    tolerant makes broker sync/backfill work with either representation.
    """
    if not isinstance(payload, dict):
        return {}
    nested = payload.get("data")
    if isinstance(nested, dict) and not any(key in payload for key in ("account", "positions", "open_orders", "orders")):
        return nested
    return payload


def _broker_state_from_execution_response(response: Any, account_id: Any, *, source: str = "manager_preflight") -> Dict[str, Any]:
    payload = _unwrap_possible_standard_response_payload(_standard_response_data(response))
    state = payload.get("broker_state") or payload.get("state") or payload
    state = _unwrap_possible_standard_response_payload(state) if isinstance(state, dict) else {}
    if not isinstance(state, dict):
        return {}

    broker_account = state.get("account") or {}
    broker_account = _unwrap_possible_standard_response_payload(broker_account) if isinstance(broker_account, dict) else {}
    positions = state.get("positions") or []
    open_orders = state.get("open_orders") or state.get("orders") or []

    return {
        "source": source,
        "account_id": account_id,
        "broker": state.get("broker") or broker_account.get("broker"),
        "paper": state.get("paper") if "paper" in state else broker_account.get("paper"),
        "captured_at": state.get("captured_at") or state.get("timestamp"),
        "account": broker_account,
        "positions": positions,
        "open_orders": open_orders,
        "summary": state.get("summary") or {
            "position_count": len(positions),
            "open_order_count": len(open_orders),
        },
    }


def _row_dict(row: Any) -> Dict[str, Any]:
    if isinstance(row, dict):
        return row
    if hasattr(row, "model_dump"):
        value = row.model_dump(mode="json")
        return value if isinstance(value, dict) else {}
    return {}


def _bucket_by_symbol_from_response(data: Dict[str, Any]) -> Dict[str, str]:
    """Build symbol -> strategy_bucket hints from Manager discovery output."""
    bucket_by_symbol: Dict[str, str] = {}
    for section in ("selected_positions", "risk_approvals", "execution_candidates"):
        for row in data.get(section) or []:
            item = _row_dict(row)
            symbol = str(item.get("symbol") or "").upper()
            bucket = str(item.get("strategy_bucket") or item.get("bucket") or "").strip().lower()
            if symbol and bucket in VALID_STRATEGY_BUCKETS:
                bucket_by_symbol[symbol] = bucket
    return bucket_by_symbol


def _enrich_broker_state_with_buckets(
    broker_state: Dict[str, Any],
    bucket_by_symbol: Dict[str, str],
) -> Dict[str, Any]:
    """Attach Manager bucket hints to broker positions and open orders."""
    if not bucket_by_symbol:
        return broker_state

    enriched = dict(broker_state)
    enriched["source"] = "manager_post_discovery_bucket_backfill"

    enriched_positions = []
    for row in broker_state.get("positions") or []:
        item = dict(_row_dict(row))
        symbol = str(item.get("symbol") or "").upper()
        bucket = bucket_by_symbol.get(symbol)
        if bucket:
            item["strategy_bucket"] = bucket
        enriched_positions.append(item)

    enriched_orders = []
    for row in broker_state.get("open_orders") or []:
        item = dict(_row_dict(row))
        symbol = str(item.get("symbol") or "").upper()
        bucket = bucket_by_symbol.get(symbol)
        if bucket:
            item["strategy_bucket"] = bucket
        enriched_orders.append(item)

    enriched["positions"] = enriched_positions
    enriched["open_orders"] = enriched_orders
    enriched["bucket_backfill"] = {
        "symbols": bucket_by_symbol,
        "source": "selected_positions",
    }
    enriched["summary"] = {
        **(enriched.get("summary") or {}),
        "bucket_hint_count": len(bucket_by_symbol),
        "bucket_position_matches": sum(1 for row in enriched_positions if row.get("strategy_bucket") in VALID_STRATEGY_BUCKETS),
        "bucket_order_matches": sum(1 for row in enriched_orders if row.get("strategy_bucket") in VALID_STRATEGY_BUCKETS),
    }
    return enriched


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


async def capture_bucket_backfilled_broker_snapshot(
    account_id: Any,
    correlation_id: str,
    bucket_by_symbol: Dict[str, str],
) -> Dict[str, Any]:
    """Persist a post-discovery broker snapshot with Manager bucket hints attached."""
    if not bucket_by_symbol:
        return {"status": "skipped", "reason": "no_bucket_hints"}

    try:
        async with ExecutionAgentClient() as exec_client:
            execution_response = await exec_client.broker_state(account_id, correlation_id)
        broker_state = _broker_state_from_execution_response(
            execution_response,
            account_id,
            source="manager_post_discovery_bucket_backfill",
        )
        if not broker_state.get("account"):
            return {"status": "skipped", "reason": "broker_state_missing_account", "bucket_hints": bucket_by_symbol}

        enriched_state = _enrich_broker_state_with_buckets(broker_state, bucket_by_symbol)
        async with DatabaseAgentClient() as db_client:
            result = await db_client.capture_broker_snapshot(enriched_state, correlation_id)

        return {
            "status": "captured",
            "result": result,
            "bucket_hints": bucket_by_symbol,
            "broker_state_summary": enriched_state.get("summary") or {},
        }
    except Exception as exc:
        report_logger.warning(
            f"Bucket backfill broker snapshot failed for account {account_id}: {exc}, correlation_id={correlation_id}"
        )
        return {"status": "failed", "error": str(exc), "bucket_hints": bucket_by_symbol}


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
            response.data["database_sync"] = database_sync
        response.data["broker_snapshot_capture"] = snapshot_capture

        bucket_by_symbol = _bucket_by_symbol_from_response(response.data)
        bucket_backfill_capture = (
            await capture_bucket_backfilled_broker_snapshot(account_id, correlation_id, bucket_by_symbol)
            if request.execute
            else {"status": "skipped", "reason": "request.execute=false"}
        )
        response.data["bucket_backfill_capture"] = bucket_backfill_capture

        if bucket_backfill_capture.get("status") == "captured":
            response.data["database_sync_after_bucket_backfill"] = await load_database_sync_status(account_id, correlation_id)

        portfolio_summary = response.data.get("portfolio_summary")
        if isinstance(portfolio_summary, dict):
            portfolio_summary["database_sync_status"] = database_sync_summary(database_sync).get("status")
            portfolio_summary["broker_snapshot_capture_status"] = snapshot_capture.get("status")
            portfolio_summary["bucket_backfill_capture_status"] = bucket_backfill_capture.get("status")
            portfolio_summary["bucket_backfill_hint_count"] = len(bucket_by_symbol)

    return response

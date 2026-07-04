"""Guarded discovery workflow entrypoint.

This module wraps the existing discovery workflow with a preflight safety gate.
Before the gate runs, it tries to capture the latest broker state into
Database_Agent so a missing snapshot can become a fresh sync result.
"""

from __future__ import annotations

import json
import os
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
DEFAULT_HELD_POSITION_BUCKET_OVERRIDES = {
    # These positions are already held in the broker account. Keep their
    # broker-sync buckets stable when a later hourly scan does not select them,
    # otherwise Database_Agent may correctly sync the row but classify it as
    # unassigned because the current response carried no bucket hint.
    "ACGL": "value_rebound",
    "ADBE": "core_dividend",
    "BKNG": "value_rebound",
    "CINF": "core_dividend",
}


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


def _normalized_strategy_bucket(value: Any) -> str:
    bucket = str(value or "").strip().lower()
    return bucket if bucket in VALID_STRATEGY_BUCKETS else ""


def _bucket_from_row(item: Dict[str, Any], *, fallback_bucket: str | None = None) -> str:
    bucket = _normalized_strategy_bucket(item.get("strategy_bucket") or item.get("bucket") or fallback_bucket)
    if bucket:
        return bucket

    for nested_name in ("score_breakdown", "analysis", "metadata", "scanner_candidate"):
        nested = item.get(nested_name)
        if isinstance(nested, dict):
            bucket = _normalized_strategy_bucket(nested.get("strategy_bucket") or nested.get("bucket"))
            if bucket:
                return bucket
    return ""


def _remember_bucket(
    bucket_by_symbol: Dict[str, str],
    row: Any,
    *,
    overwrite: bool,
    fallback_bucket: str | None = None,
) -> None:
    item = _row_dict(row)
    symbol = str(item.get("symbol") or item.get("ticker") or "").strip().upper()
    bucket = _bucket_from_row(item, fallback_bucket=fallback_bucket)
    if not symbol or not bucket:
        return
    if overwrite:
        bucket_by_symbol[symbol] = bucket
    else:
        bucket_by_symbol.setdefault(symbol, bucket)


def _remember_bucket_selection(bucket_by_symbol: Dict[str, str], bucket_selection: Any) -> None:
    """Capture bucket hints from allocation bucket_selection.

    `bucket_selection` is keyed by bucket name and may contain selected/overflow
    rows that do not repeat `strategy_bucket`, so the parent bucket key is used as
    a safe fallback. Only valid configured bucket names are accepted.
    """
    if not isinstance(bucket_selection, dict):
        return

    for bucket_name, bucket_payload in bucket_selection.items():
        fallback_bucket = _normalized_strategy_bucket(bucket_name)
        if not fallback_bucket or not isinstance(bucket_payload, dict):
            continue
        for section in ("selected", "overflow"):
            for row in bucket_payload.get(section) or []:
                _remember_bucket(bucket_by_symbol, row, overwrite=True, fallback_bucket=fallback_bucket)


def _configured_held_position_bucket_overrides() -> Dict[str, str]:
    """Return symbol -> bucket overrides for already-held broker positions.

    The default map keeps known held positions from becoming `unassigned` when
    they are absent from the current discovery selection. Operators can extend or
    replace values with MANAGER_POSITION_BUCKET_OVERRIDES_JSON, for example:
    {"CINF": "core_dividend"}.
    """
    overrides: Dict[str, str] = dict(DEFAULT_HELD_POSITION_BUCKET_OVERRIDES)
    raw = os.getenv("MANAGER_POSITION_BUCKET_OVERRIDES_JSON", "").strip()
    if not raw:
        return overrides

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        report_logger.warning(f"Invalid MANAGER_POSITION_BUCKET_OVERRIDES_JSON ignored: {exc}")
        return overrides

    if not isinstance(parsed, dict):
        report_logger.warning("MANAGER_POSITION_BUCKET_OVERRIDES_JSON must be a JSON object; ignoring override payload")
        return overrides

    for symbol, bucket in parsed.items():
        normalized_symbol = str(symbol or "").strip().upper()
        normalized_bucket = _normalized_strategy_bucket(bucket)
        if normalized_symbol and normalized_bucket:
            overrides[normalized_symbol] = normalized_bucket
    return overrides


def _bucket_by_symbol_from_database_sync(database_sync: Dict[str, Any]) -> Dict[str, str]:
    """Build symbol -> bucket hints from the latest Database_Agent broker snapshot."""
    bucket_by_symbol: Dict[str, str] = {}
    if not isinstance(database_sync, dict):
        return bucket_by_symbol

    snapshots = []
    latest_snapshot = database_sync.get("latest_snapshot")
    if isinstance(latest_snapshot, dict):
        snapshots.append(latest_snapshot)
    database = database_sync.get("database")
    if isinstance(database, dict):
        snapshots.append(database)

    for snapshot in snapshots:
        for section in ("positions", "open_orders", "orders"):
            for row in snapshot.get(section) or []:
                _remember_bucket(bucket_by_symbol, row, overwrite=False)

    return bucket_by_symbol


def _preflight_bucket_by_symbol_from_database_sync(database_sync: Dict[str, Any]) -> Dict[str, str]:
    """Return stable preflight bucket hints for held broker positions.

    The preflight broker sync runs before the current scan has selected/ranked
    rows. It must still carry stable held-position buckets so Database_Agent does
    not create an interim snapshot where known holdings become `unassigned`.
    Last known Database_Agent buckets win over defaults; invalid/unassigned rows
    are ignored by _bucket_by_symbol_from_database_sync.
    """
    bucket_by_symbol = dict(_configured_held_position_bucket_overrides())
    bucket_by_symbol.update(_bucket_by_symbol_from_database_sync(database_sync))
    return bucket_by_symbol


def _bucket_by_symbol_from_response(data: Dict[str, Any], database_sync: Dict[str, Any] | None = None) -> Dict[str, str]:
    """Build symbol -> strategy_bucket hints for broker snapshot backfill.

    Priority order:
    1. current Manager discovery output from selected/skipped/ranked rows,
    2. current allocation bucket_selection parent buckets,
    3. the last known bucket already stored in Database_Agent,
    4. configured held-position overrides,
    5. otherwise no hint, so Database_Agent may keep the row unassigned.
    """
    bucket_by_symbol: Dict[str, str] = {}
    for section in (
        "selected_positions",
        "skipped_existing_protected_positions",
        "risk_approvals",
        "execution_candidates",
        "position_analysis_payloads",
        "ranked_candidates",
    ):
        for row in data.get(section) or []:
            _remember_bucket(bucket_by_symbol, row, overwrite=True)

    _remember_bucket_selection(bucket_by_symbol, data.get("bucket_selection"))

    for symbol, bucket in _bucket_by_symbol_from_database_sync(database_sync or {}).items():
        bucket_by_symbol.setdefault(symbol, bucket)

    for symbol, bucket in _configured_held_position_bucket_overrides().items():
        bucket_by_symbol.setdefault(symbol, bucket)
    return bucket_by_symbol


def _enrich_broker_state_with_buckets(
    broker_state: Dict[str, Any],
    bucket_by_symbol: Dict[str, str],
    *,
    source: str = "selected_positions_database_snapshot_and_held_position_overrides",
) -> Dict[str, Any]:
    """Attach Manager/Database bucket hints to broker positions and open orders."""
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
        "source": source,
    }
    enriched["summary"] = {
        **(enriched.get("summary") or {}),
        "bucket_hint_count": len(bucket_by_symbol),
        "bucket_position_matches": sum(1 for row in enriched_positions if row.get("strategy_bucket") in VALID_STRATEGY_BUCKETS),
        "bucket_order_matches": sum(1 for row in enriched_orders if row.get("strategy_bucket") in VALID_STRATEGY_BUCKETS),
    }
    return enriched


async def capture_broker_snapshot(
    account_id: Any,
    correlation_id: str,
    bucket_by_symbol: Dict[str, str] | None = None,
) -> Dict[str, Any]:
    """Fetch current broker state from Execution_Agent and persist it to Database_Agent."""
    try:
        async with ExecutionAgentClient() as exec_client:
            execution_response = await exec_client.broker_state(account_id, correlation_id)
        broker_state = _broker_state_from_execution_response(execution_response, account_id)
        if not broker_state.get("account"):
            return {"status": "skipped", "reason": "broker_state_missing_account"}
        if bucket_by_symbol:
            broker_state = _enrich_broker_state_with_buckets(
                broker_state,
                bucket_by_symbol,
                source="previous_database_snapshot_and_held_position_overrides",
            )
            broker_state["source"] = "manager_preflight_preserve_database_buckets"
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
    previous_database_sync = await load_database_sync_status(account_id, correlation_id) if request.execute else {}
    preflight_bucket_by_symbol = _preflight_bucket_by_symbol_from_database_sync(previous_database_sync)
    snapshot_capture = (
        await capture_broker_snapshot(account_id, correlation_id, preflight_bucket_by_symbol)
        if request.execute
        else {"status": "skipped", "reason": "request.execute=false"}
    )
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

        bucket_by_symbol = _bucket_by_symbol_from_response(response.data, previous_database_sync or database_sync)
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

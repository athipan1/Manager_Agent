"""Guarded discovery workflow with the Exposure-Aware Trade Gate enabled."""

from __future__ import annotations

import datetime
from typing import Any, Dict

from ..contracts import StandardAgentResponse
from ..models import DiscoverAnalyzeTradeRequest
from ..services.database_sync_gate import (
    database_sync_allows_automation,
    database_sync_summary,
)
from .gated_discovery_workflow import run_gated_discover_analyze_trade_flow
from .guarded_discovery_workflow import (
    _bucket_by_symbol_from_response,
    _preflight_bucket_by_symbol_from_database_sync,
    _request_with_execution_disabled,
    _with_blocked_execution,
    capture_broker_snapshot,
    capture_bucket_backfilled_broker_snapshot,
    load_database_sync_status,
)

_TIMESTAMP_KEYS = (
    "captured_at",
    "snapshot_at",
    "timestamp",
    "created_at",
    "updated_at",
)


def _parse_timestamp(value: Any) -> datetime.datetime | None:
    if not value:
        return None
    if isinstance(value, datetime.datetime):
        parsed = value
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.UTC)
    return parsed.astimezone(datetime.UTC)


def _find_snapshot_timestamp(value: Any) -> datetime.datetime | None:
    if isinstance(value, dict):
        for key in _TIMESTAMP_KEYS:
            parsed = _parse_timestamp(value.get(key))
            if parsed is not None:
                return parsed
        for key in (
            "latest_snapshot",
            "database",
            "broker",
            "mismatch",
            "summary",
            "diagnostics",
        ):
            parsed = _find_snapshot_timestamp(value.get(key))
            if parsed is not None:
                return parsed
        for nested in value.values():
            parsed = _find_snapshot_timestamp(nested)
            if parsed is not None:
                return parsed
    elif isinstance(value, list):
        for nested in value:
            parsed = _find_snapshot_timestamp(nested)
            if parsed is not None:
                return parsed
    return None


def database_snapshot_age_seconds(
    database_sync: Dict[str, Any],
    *,
    now: datetime.datetime | None = None,
) -> float | None:
    """Return the age of the freshest observable broker/database snapshot."""
    captured_at = _find_snapshot_timestamp(database_sync)
    if captured_at is None:
        return None
    current = now or datetime.datetime.now(datetime.UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=datetime.UTC)
    return max(
        0.0,
        (current.astimezone(datetime.UTC) - captured_at).total_seconds(),
    )


async def run_gated_guarded_discover_analyze_trade_flow(
    request: DiscoverAnalyzeTradeRequest,
) -> StandardAgentResponse:
    """Run broker sync safety, exposure gating, risk and optional execution."""
    correlation_id = "database-sync-gate"
    account_id = request.account_id if request.account_id is not None else 1

    previous_database_sync = (
        await load_database_sync_status(account_id, correlation_id)
        if request.execute
        else {}
    )
    preflight_bucket_by_symbol = (
        _preflight_bucket_by_symbol_from_database_sync(
            previous_database_sync
        )
    )
    snapshot_capture = (
        await capture_broker_snapshot(
            account_id,
            correlation_id,
            preflight_bucket_by_symbol,
        )
        if request.execute
        else {"status": "skipped", "reason": "request.execute=false"}
    )
    database_sync = await load_database_sync_status(
        account_id,
        correlation_id,
    )
    sync_allows_automation = database_sync_allows_automation(database_sync)
    snapshot_age_seconds = database_snapshot_age_seconds(database_sync)

    if request.execute and not sync_allows_automation:
        analysis_only_request = _request_with_execution_disabled(request)
        response = await run_gated_discover_analyze_trade_flow(
            analysis_only_request,
            database_sync_ok=False,
            snapshot_age_seconds=snapshot_age_seconds,
        )
        return _with_blocked_execution(
            response,
            database_sync,
            snapshot_capture,
        )

    response = await run_gated_discover_analyze_trade_flow(
        request,
        database_sync_ok=(
            sync_allows_automation if request.execute else True
        ),
        snapshot_age_seconds=(
            snapshot_age_seconds if request.execute else None
        ),
    )

    if isinstance(response.data, dict):
        if database_sync:
            response.data["database_sync"] = database_sync
        response.data["broker_snapshot_capture"] = snapshot_capture

        bucket_by_symbol = _bucket_by_symbol_from_response(
            response.data,
            previous_database_sync or database_sync,
        )
        bucket_backfill_capture = (
            await capture_bucket_backfilled_broker_snapshot(
                account_id,
                correlation_id,
                bucket_by_symbol,
            )
            if request.execute
            else {"status": "skipped", "reason": "request.execute=false"}
        )
        response.data["bucket_backfill_capture"] = bucket_backfill_capture

        if bucket_backfill_capture.get("status") == "captured":
            response.data["database_sync_after_bucket_backfill"] = (
                await load_database_sync_status(
                    account_id,
                    correlation_id,
                )
            )

        portfolio_summary = response.data.get("portfolio_summary")
        if isinstance(portfolio_summary, dict):
            portfolio_summary["database_sync_status"] = (
                database_sync_summary(database_sync).get("status")
            )
            portfolio_summary["broker_snapshot_capture_status"] = (
                snapshot_capture.get("status")
            )
            portfolio_summary["bucket_backfill_capture_status"] = (
                bucket_backfill_capture.get("status")
            )
            portfolio_summary["bucket_backfill_hint_count"] = len(
                bucket_by_symbol
            )
            portfolio_summary["database_snapshot_age_seconds"] = (
                snapshot_age_seconds
            )

    return response

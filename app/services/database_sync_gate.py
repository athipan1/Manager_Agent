"""Safety helpers for Broker/Database sync status.

These helpers keep order-entry workflows from relying on stale Database context
when Database_Agent reports that its Broker snapshot is missing or mismatched.
"""

from __future__ import annotations

from typing import Any, Dict

UNSAFE_DATABASE_SYNC_STATUSES = {"mismatch", "no_snapshot", "unavailable", "error", "failed"}


def database_sync_summary(database_sync: Dict[str, Any] | None) -> Dict[str, Any]:
    mismatch = database_sync.get("mismatch") if isinstance(database_sync, dict) else {}
    summary = mismatch.get("summary") if isinstance(mismatch, dict) else {}
    return summary if isinstance(summary, dict) else {}


def database_sync_status(database_sync: Dict[str, Any] | None) -> str:
    return str(database_sync_summary(database_sync).get("status") or "").strip().lower()


def database_sync_allows_automation(database_sync: Dict[str, Any] | None) -> bool:
    """Return True when the sync status is safe or unknown for legacy clients."""
    status = database_sync_status(database_sync)
    if not status:
        return True
    return status not in UNSAFE_DATABASE_SYNC_STATUSES


def database_sync_block_reason(database_sync: Dict[str, Any] | None) -> str:
    summary = database_sync_summary(database_sync)
    action = summary.get("recommended_action") or "refresh_broker_sync"
    status = summary.get("status") or "unknown"
    return f"Database/Broker sync status is {status}; recommended_action={action}."


def database_sync_blocked_execution(database_sync: Dict[str, Any] | None) -> Dict[str, Any]:
    return {
        "status": "blocked",
        "reason": database_sync_block_reason(database_sync),
        "database_sync_summary": database_sync_summary(database_sync),
        "database_sync": database_sync or {},
    }

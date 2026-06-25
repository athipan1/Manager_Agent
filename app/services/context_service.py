"""Context loading helpers for Manager_Agent.

This module centralizes the portfolio/session context reads that Manager uses
before risk evaluation. LIVE mode must fail closed when required context cannot
be loaded; PAPER mode may use safe fallback values.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal
from typing import Any, Dict, Iterable, Union

from .. import config
from ..context_numbers import active_value
from ..database_client import DatabaseAgentClient
from ..logger import report_logger
from ..resilient_client import AgentUnavailable
from .serialization_service import dict_or_empty


def _fallback_session_context() -> Dict[str, Any]:
    """Return the PAPER-mode safe fallback session risk context."""
    return {
        "daily_realized_pnl": 0.0,
        "weekly_realized_pnl": 0.0,
        "consecutive_losses": 0,
        "trades_today": 0,
        "symbol_trades_today": 0,
        "minutes_since_last_loss": None,
        "minutes_since_last_symbol_trade": None,
        "emergency_halt": bool(getattr(config, "MANAGER_EMERGENCY_HALT", False)),
        "source": "manager_fallback",
    }


async def fetch_context_value(
    db_client: DatabaseAgentClient,
    account_id: Union[int, str],
    correlation_id: str,
) -> Decimal:
    """Return active open-order exposure from Database_Agent.

    LIVE mode fails closed if the context cannot be loaded. PAPER mode falls
    back to zero exposure, matching the legacy Manager behavior.
    """
    try:
        rows = await db_client.get_orders(account_id, correlation_id)
        return active_value(rows)
    except Exception as exc:
        if config.TRADING_MODE == "LIVE":
            raise AgentUnavailable(f"Required portfolio context unavailable: {exc}") from exc
        report_logger.warning(
            "Portfolio context unavailable in PAPER mode; using zero value. "
            f"correlation_id={correlation_id}: {exc}"
        )
        return Decimal("0")


async def fetch_session_risk_context(
    db_client: DatabaseAgentClient,
    account_id: Union[int, str],
    symbol: str,
    correlation_id: str,
) -> Dict[str, Any]:
    """Return session risk snapshot for one symbol.

    LIVE mode fails closed if Database_Agent cannot provide the snapshot. PAPER
    mode uses a safe zero/default context.
    """
    try:
        snapshot = await db_client.get_session_risk_snapshot(
            account_id,
            correlation_id,
            symbol=symbol,
        )
        snapshot = dict_or_empty(snapshot)
        snapshot.setdefault("emergency_halt", bool(getattr(config, "MANAGER_EMERGENCY_HALT", False)))
        if getattr(config, "MANAGER_EMERGENCY_HALT", False):
            snapshot["emergency_halt"] = True
        return snapshot
    except Exception as exc:
        if config.TRADING_MODE == "LIVE":
            raise AgentUnavailable(f"Required session risk context unavailable for {symbol}: {exc}") from exc
        report_logger.warning(
            f"Session risk context unavailable in PAPER mode for {symbol}; "
            f"using safe zero context. correlation_id={correlation_id}: {exc}"
        )
        return _fallback_session_context()


async def fetch_session_risk_contexts(
    db_client: DatabaseAgentClient,
    account_id: Union[int, str],
    symbols: Iterable[str],
    correlation_id: str,
) -> Dict[str, Any]:
    """Return shared and per-symbol session risk context for multiple symbols."""
    unique_symbols = [symbol for symbol in dict.fromkeys([str(s).upper() for s in symbols if s])]
    if not unique_symbols:
        return {}

    snapshots = await asyncio.gather(
        *[
            fetch_session_risk_context(db_client, account_id, symbol, correlation_id)
            for symbol in unique_symbols
        ]
    )
    snapshots = [dict_or_empty(snapshot) for snapshot in snapshots]
    first = snapshots[0] if snapshots else {}
    shared = {
        key: first.get(key)
        for key in [
            "daily_realized_pnl",
            "weekly_realized_pnl",
            "consecutive_losses",
            "trades_today",
            "minutes_since_last_loss",
            "emergency_halt",
        ]
        if key in first
    }
    shared["symbol_contexts"] = {
        symbol: snapshot
        for symbol, snapshot in zip(unique_symbols, snapshots)
    }
    return shared

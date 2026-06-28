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
from ..performance_agent_client import PerformanceAgentClient
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


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _trade_realized_pnl(trade: Any) -> float:
    entry_price = getattr(trade, "entry_price", None)
    exit_price = getattr(trade, "exit_price", None)
    quantity = _as_float(getattr(trade, "quantity", 0.0))
    side = str(getattr(trade, "side", "buy") or "buy").lower()
    if entry_price is not None and exit_price is not None and quantity > 0:
        entry = _as_float(entry_price)
        exit_ = _as_float(exit_price)
        multiplier = -1.0 if side in {"sell", "short"} else 1.0
        return round((exit_ - entry) * quantity * multiplier, 2)
    pnl_pct = getattr(trade, "pnl_pct", None)
    price = _as_float(getattr(trade, "price", 0.0))
    if pnl_pct is not None and price > 0 and quantity > 0:
        return round(price * quantity * _as_float(pnl_pct), 2)
    return 0.0


def _trade_to_session_fill(trade: Any) -> Dict[str, Any]:
    return {
        "trade_id": str(getattr(trade, "trade_id", "")),
        "symbol": str(getattr(trade, "symbol", "")).upper(),
        "side": str(getattr(trade, "side", "buy") or "buy"),
        "quantity": _as_float(getattr(trade, "quantity", 0.0), 0.0),
        "fill_price": _as_float(getattr(trade, "price", None) or getattr(trade, "exit_price", None) or getattr(trade, "entry_price", None), 0.0),
        "realized_pnl": _trade_realized_pnl(trade),
        "filled_at": getattr(trade, "executed_at", None),
    }


def _merge_session_context(database_snapshot: Dict[str, Any], performance_metrics: Dict[str, Any]) -> Dict[str, Any]:
    merged = {
        **dict_or_empty(database_snapshot),
        **dict_or_empty(performance_metrics),
    }
    merged["source"] = "performance_agent" if performance_metrics else merged.get("source", "database_agent")
    if getattr(config, "MANAGER_EMERGENCY_HALT", False):
        merged["emergency_halt"] = True
    else:
        merged.setdefault("emergency_halt", False)
    return merged


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


async def _fetch_performance_session_risk_context(
    db_client: DatabaseAgentClient,
    account_id: Union[int, str],
    symbol: str,
    equity: Any,
    database_snapshot: Dict[str, Any],
    correlation_id: str,
) -> Dict[str, Any]:
    if not config.PERFORMANCE_SESSION_RISK_ENABLED:
        return {}
    trades = await db_client.get_trade_history(account_id, correlation_id)
    fills = [
        _trade_to_session_fill(trade)
        for trade in trades[: config.PERFORMANCE_SESSION_RISK_FILL_LIMIT]
        if _as_float(getattr(trade, "quantity", 0.0)) > 0
    ]
    payload = {
        "account_id": account_id,
        "symbol": symbol,
        "equity": _as_float(equity, 1.0),
        "fills": fills,
        "emergency_halt": bool(database_snapshot.get("emergency_halt") or getattr(config, "MANAGER_EMERGENCY_HALT", False)),
    }
    async with PerformanceAgentClient() as performance_client:
        return await performance_client.build_session_risk_metrics(payload, correlation_id)


async def fetch_session_risk_context(
    db_client: DatabaseAgentClient,
    account_id: Union[int, str],
    symbol: str,
    correlation_id: str,
    equity: Any = None,
) -> Dict[str, Any]:
    """Return session risk snapshot for one symbol.

    Database_Agent remains the baseline source of session state. When enabled,
    Performance_Agent recalculates realized PnL, loss streak, and trade counters
    from fills/trade history so Risk_Agent receives kill-switch context based on
    recent performance.
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
        try:
            performance_metrics = await _fetch_performance_session_risk_context(
                db_client=db_client,
                account_id=account_id,
                symbol=symbol,
                equity=equity,
                database_snapshot=snapshot,
                correlation_id=correlation_id,
            )
            return _merge_session_context(snapshot, performance_metrics)
        except Exception as perf_exc:
            if config.TRADING_MODE == "LIVE" and config.PERFORMANCE_SESSION_RISK_REQUIRED:
                raise AgentUnavailable(f"Required performance session risk metrics unavailable for {symbol}: {perf_exc}") from perf_exc
            report_logger.warning(
                f"Performance session risk metrics unavailable for {symbol}; using Database session snapshot. "
                f"correlation_id={correlation_id}: {perf_exc}"
            )
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
    equity: Any = None,
) -> Dict[str, Any]:
    """Return shared and per-symbol session risk context for multiple symbols."""
    unique_symbols = [symbol for symbol in dict.fromkeys([str(s).upper() for s in symbols if s])]
    if not unique_symbols:
        return {}

    snapshots = await asyncio.gather(
        *[
            fetch_session_risk_context(db_client, account_id, symbol, correlation_id, equity=equity)
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

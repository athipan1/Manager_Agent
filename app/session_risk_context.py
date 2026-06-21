from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, Optional


TERMINAL_LOSS_STATUSES = {"executed", "failed", "cancelled", "canceled"}
IN_FLIGHT_ORDER_STATUSES = {"pending", "placed", "partially_filled"}


def _as_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None:
            return default
        return Decimal(str(value))
    except Exception:
        return default


def _as_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        raw = str(value).replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _symbol_of(row: Dict[str, Any]) -> str:
    return str(row.get("symbol") or "").upper()


def _status_of(row: Dict[str, Any]) -> str:
    return str(row.get("status") or "").lower()


def _row_timestamp(row: Dict[str, Any]) -> Optional[datetime]:
    return _as_datetime(row.get("executed_at") or row.get("timestamp") or row.get("updated_at") or row.get("created_at"))


def _realized_pnl(row: Dict[str, Any]) -> Decimal:
    # Prefer explicit PnL fields when Database Agent provides them.
    for key in ("realized_pnl", "pnl", "profit_loss", "net_pnl"):
        if key in row and row.get(key) is not None:
            return _as_decimal(row.get(key))

    metadata = row.get("metadata") or {}
    if isinstance(metadata, dict):
        for key in ("realized_pnl", "pnl", "profit_loss", "net_pnl"):
            if key in metadata and metadata.get(key) is not None:
                return _as_decimal(metadata.get(key))

    # Without cost-basis/fill accounting, do not invent PnL.
    return Decimal("0")


def _minutes_since(dt: Optional[datetime], now: datetime) -> Optional[float]:
    if not dt:
        return None
    return max(0.0, (now - dt).total_seconds() / 60.0)


def _trades_in_window(rows: Iterable[Dict[str, Any]], start: datetime, *, symbol: Optional[str] = None) -> list[Dict[str, Any]]:
    symbol_upper = symbol.upper() if symbol else None
    result: list[Dict[str, Any]] = []
    for row in rows:
        timestamp = _row_timestamp(row)
        if not timestamp or timestamp < start:
            continue
        if symbol_upper and _symbol_of(row) != symbol_upper:
            continue
        if _status_of(row) not in TERMINAL_LOSS_STATUSES:
            continue
        result.append(row)
    return result


def _consecutive_losses(rows: list[Dict[str, Any]]) -> int:
    ordered = sorted(rows, key=lambda row: _row_timestamp(row) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    losses = 0
    for row in ordered:
        pnl = _realized_pnl(row)
        if pnl < 0:
            losses += 1
            continue
        if pnl > 0:
            break
    return losses


def build_session_risk_context(
    *,
    account_id: Any,
    symbol: str,
    orders: list[Dict[str, Any]],
    trades: Optional[list[Dict[str, Any]]] = None,
    emergency_halt: bool = False,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Build the context Risk_Agent requires for session/circuit-breaker checks.

    The function is deterministic and tolerant of partial Database Agent payloads.
    If explicit trade PnL is unavailable, PnL defaults to zero instead of guessing.
    """
    now = now or datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = day_start - timedelta(days=day_start.weekday())

    history_rows = list(trades or []) or [row for row in orders if _status_of(row) in TERMINAL_LOSS_STATUSES]
    daily_rows = _trades_in_window(history_rows, day_start)
    weekly_rows = _trades_in_window(history_rows, week_start)
    daily_symbol_rows = _trades_in_window(history_rows, day_start, symbol=symbol)

    latest_loss_time = None
    for row in sorted(history_rows, key=lambda item: _row_timestamp(item) or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
        if _realized_pnl(row) < 0:
            latest_loss_time = _row_timestamp(row)
            break

    latest_symbol_trade_time = None
    for row in sorted(daily_symbol_rows, key=lambda item: _row_timestamp(item) or datetime.min.replace(tzinfo=timezone.utc), reverse=True):
        latest_symbol_trade_time = _row_timestamp(row)
        break

    return {
        "account_id": account_id,
        "symbol": symbol.upper(),
        "daily_realized_pnl": float(sum((_realized_pnl(row) for row in daily_rows), Decimal("0"))),
        "weekly_realized_pnl": float(sum((_realized_pnl(row) for row in weekly_rows), Decimal("0"))),
        "consecutive_losses": _consecutive_losses(history_rows),
        "trades_today": len(daily_rows),
        "symbol_trades_today": len(daily_symbol_rows),
        "minutes_since_last_loss": _minutes_since(latest_loss_time, now),
        "minutes_since_last_symbol_trade": _minutes_since(latest_symbol_trade_time, now),
        "emergency_halt": bool(emergency_halt),
    }

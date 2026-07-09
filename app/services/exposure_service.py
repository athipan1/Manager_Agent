"""Exposure calculation and request-local position snapshot helpers."""

from __future__ import annotations

from contextvars import ContextVar
from decimal import Decimal
from typing import Any, Iterable, Tuple

from .serialization_service import as_decimal


_POSITION_SNAPSHOT: ContextVar[Tuple[Any, ...]] = ContextVar(
    "manager_position_snapshot",
    default=(),
)


def position_exposure(position: Any) -> Decimal:
    """Return absolute notional exposure for a single position."""
    if not position:
        return Decimal("0")
    market_value = as_decimal(
        getattr(position, "market_value", None)
        if not isinstance(position, dict)
        else position.get("market_value")
    )
    if market_value:
        return abs(market_value)
    if isinstance(position, dict):
        qty = as_decimal(
            position.get("quantity")
            or position.get("qty")
            or position.get("owned_quantity")
            or 0
        )
        price = as_decimal(
            position.get("current_market_price")
            or position.get("current_price")
            or position.get("average_cost")
            or position.get("avg_entry_price")
        )
    else:
        qty = as_decimal(
            getattr(position, "quantity", None)
            or getattr(position, "qty", None)
            or 0
        )
        price = as_decimal(
            getattr(position, "current_market_price", None)
            or getattr(position, "current_price", None)
            or getattr(position, "average_cost", None)
            or getattr(position, "avg_entry_price", None)
        )
    return abs(qty * price)


def capture_position_snapshot(positions: Iterable[Any]) -> Tuple[Any, ...]:
    """Store an immutable position list in the current async request context."""
    snapshot = tuple(positions or ())
    _POSITION_SNAPSHOT.set(snapshot)
    return snapshot


def current_position_snapshot() -> list[Any]:
    """Return the positions captured for the current request/task only."""
    return list(_POSITION_SNAPSHOT.get())


def clear_position_snapshot() -> None:
    """Clear the current request's captured position context."""
    _POSITION_SNAPSHOT.set(())


def total_position_exposure(positions: Iterable[Any]) -> Decimal:
    """Return total exposure and retain the request-local position snapshot.

    Discovery computes portfolio value immediately before allocation. Capturing
    the same immutable rows here lets the capacity selector use the exact
    portfolio state without module globals or cross-request leakage.
    """
    snapshot = capture_position_snapshot(positions)
    return sum(
        (position_exposure(position) for position in snapshot),
        Decimal("0"),
    )

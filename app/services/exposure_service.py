"""Pure exposure calculation helpers for Manager_Agent."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable

from .serialization_service import as_decimal


def position_exposure(position: Any) -> Decimal:
    """Return absolute notional exposure for a single position."""
    if not position:
        return Decimal("0")

    qty = as_decimal(getattr(position, "quantity", 0))
    price = as_decimal(
        getattr(position, "current_market_price", None)
        or getattr(position, "average_cost", None)
    )
    return abs(qty * price)


def total_position_exposure(positions: Iterable[Any]) -> Decimal:
    """Return total absolute notional exposure across positions."""
    return sum((position_exposure(position) for position in positions), Decimal("0"))

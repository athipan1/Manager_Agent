from decimal import Decimal
from typing import Any, Dict, List

ACTIVE = {"pending", "placed", "partially_filled"}


def to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None:
            return default
        return Decimal(str(value))
    except Exception:
        return default


def as_dict(item: Any) -> Dict[str, Any]:
    if isinstance(item, dict):
        return item
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    return {}


def active_value(rows: List[Any]) -> Decimal:
    total = Decimal("0")
    for item in rows:
        row = as_dict(item)
        if str(row.get("status") or "").lower() not in ACTIVE:
            continue
        amount = to_decimal(row.get("quantity")) - to_decimal(row.get("executed_quantity"))
        value = to_decimal(row.get("price") or row.get("limit_price") or row.get("avg_execution_price"))
        if amount > 0 and value > 0:
            total += abs(amount * value)
    return total

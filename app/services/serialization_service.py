"""Pure serialization and normalization helpers for Manager_Agent.

These helpers are intentionally side-effect free so they can be unit tested
without starting FastAPI or any downstream trading agents.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any, Dict

from ..contracts import StandardAgentResponse


def response_to_dict(resp: StandardAgentResponse | Dict[str, Any] | Any) -> Dict[str, Any]:
    """Convert supported response objects into plain dictionaries."""
    if isinstance(resp, StandardAgentResponse):
        return resp.model_dump(mode="json")
    if isinstance(resp, dict):
        return resp
    if hasattr(resp, "model_dump"):
        return resp.model_dump(mode="json")
    return {}


def normalize_score(value: Any) -> float:
    """Normalize a score into the inclusive 0.0-1.0 range.

    Values greater than 1 are treated as percentage-style values and divided by
    100. Invalid values fail safe to 0.0.
    """
    try:
        score = float(value or 0.0)
        score = score / 100.0 if score > 1.0 else score
        return max(0.0, min(1.0, score))
    except (TypeError, ValueError):
        return 0.0


def agent_data(resp: StandardAgentResponse | Dict[str, Any] | Any) -> Dict[str, Any]:
    """Extract the nested `data` object from an agent response as a dict."""
    data = response_to_dict(resp).get("data") or {}
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    return data if isinstance(data, dict) else {}


def as_decimal(value: Any) -> Decimal:
    """Safely convert values into Decimal, failing safe to Decimal('0')."""
    try:
        if value is None:
            return Decimal("0")
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def jsonable(value: Any) -> Any:
    """Convert common non-JSON types into JSON-compatible values."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    return value


def dict_or_empty(value: Any) -> Dict[str, Any]:
    """Return `value` when it is a dict; otherwise return an empty dict."""
    return value if isinstance(value, dict) else {}

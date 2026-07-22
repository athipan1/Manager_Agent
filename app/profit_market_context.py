from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


MARKET_CONTEXT_VERSION = "profit-market-context.v1"
TECHNICAL_CONTEXT_VERSION = "profit-technical-context.v1"
VALID_REGIMES = {"BULL", "BEAR", "SIDEWAYS", "VOLATILE"}
VALID_RISK_LEVELS = {"LOW", "MEDIUM", "HIGH"}


def _dict(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    data = value.get("data")
    return data if isinstance(data, dict) else value


def _aware_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _is_fresh(observed_at: datetime, now: datetime, max_age_seconds: int) -> bool:
    age = (now - observed_at).total_seconds()
    return 0 <= age <= max_age_seconds


def _holding_days(position: dict[str, Any], now: datetime) -> int | None:
    for key in ("opened_at", "entry_at", "opened_timestamp", "created_at"):
        opened_at = _aware_datetime(position.get(key))
        if opened_at is not None and opened_at <= now:
            return max(0, (now - opened_at).days)
    return None


def compose_profit_market_context(
    *,
    market_regime: Any,
    technical_analysis: Any,
    position: dict[str, Any],
    lifecycle_available: bool,
    max_age_seconds: int = 120,
    emergency_halt_active: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compose evidence without inventing missing upstream measurements."""
    if max_age_seconds <= 0:
        raise ValueError("max_age_seconds must be positive")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    market = _dict(market_regime)
    technical = _dict(technical_analysis)
    market_projection = _dict(market.get("profit_policy_context"))
    technical_projection = _dict(technical.get("profit_policy_context"))
    warnings: list[str] = []

    if market_projection.get("context_version") != MARKET_CONTEXT_VERSION:
        warnings.append("Market Regime profit context is missing or has an unsupported version")
        market_projection = {}
    if technical_projection and (
        technical_projection.get("context_version") != TECHNICAL_CONTEXT_VERSION
    ):
        warnings.append("Technical profit context has an unsupported version and was ignored")
        technical_projection = {}
    elif technical_projection and technical_projection.get("evidence_status") not in {
        "complete",
        "partial",
    }:
        warnings.append("Technical profit context lacks usable evidence and was ignored")
        technical_projection = {}
    elif not technical_projection:
        warnings.append("Technical profit context is unavailable; no technical fields were inferred")

    regime = str(market_projection.get("regime") or "").upper()
    risk_level = str(market_projection.get("risk_level") or "").upper()
    market_context: dict[str, Any] | None = None
    observed: list[datetime] = []
    freshness_complete = False
    if regime in VALID_REGIMES and risk_level in VALID_RISK_LEVELS:
        market_context = {"regime": regime, "risk_level": risk_level}
        for field in ("atr_pct", "volatility_percentile", "trend_strength"):
            value = market_projection.get(field)
            if value is not None:
                market_context[field] = value
        for field in ("atr_pct", "trend_strength", "volume_strength"):
            value = technical_projection.get(field)
            if value is not None:
                market_context[field] = value

        market_observed_at = _aware_datetime(market_projection.get("observed_at"))
        freshness_complete = market_observed_at is not None
        if market_observed_at is not None:
            observed.append(market_observed_at)
        technical_observed_at = _aware_datetime(
            technical_projection.get("observed_at")
        )
        if technical_projection and technical_observed_at is not None:
            observed.append(technical_observed_at)
        if technical_projection and technical_observed_at is None:
            freshness_complete = False
        if observed:
            market_context["observed_at"] = min(observed).isoformat().replace(
                "+00:00", "Z"
            )

        holding_days = _holding_days(position, now)
        if holding_days is not None:
            market_context["holding_days"] = holding_days
        if isinstance(position.get("upcoming_event_risk"), bool):
            market_context["upcoming_event_risk"] = position[
                "upcoming_event_risk"
            ]
    else:
        warnings.append("Market Regime context is incomplete; adaptive policy is blocked")

    peak_complete = (
        position.get("highest_price_since_entry") not in (None, "")
        and position.get("highest_price_since_entry_source") == "database_agent"
    )
    market_price_fresh = freshness_complete and bool(observed) and all(
        _is_fresh(value, now, max_age_seconds) for value in observed
    )
    if not market_price_fresh:
        warnings.append("Profit market context freshness could not be proven")
    if not peak_complete:
        warnings.append("Database-owned position peak history is incomplete")
    if not lifecycle_available:
        warnings.append("Database position version is unavailable")

    result: dict[str, Any] = {
        "data_quality": {
            "market_price_fresh": market_price_fresh,
            "peak_history_complete": peak_complete,
            "position_version_current": lifecycle_available,
            "emergency_halt_active": emergency_halt_active,
        },
        "warnings": list(dict.fromkeys(warnings)),
    }
    if market_context is not None:
        result["market_context"] = market_context
    return result

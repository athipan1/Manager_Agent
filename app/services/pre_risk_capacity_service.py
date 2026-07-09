"""Capacity-aware selection before Manager calls Risk_Agent.

This module mirrors the stable stock exposure defaults used by Risk_Agent so
Manager can avoid sending obviously impossible BUY candidates downstream. Risk
remains authoritative and still re-checks every accepted candidate.
"""

from __future__ import annotations

import os
from copy import deepcopy
from decimal import Decimal
from typing import Any, Dict, Iterable, Mapping, Optional

from ..discover_allocation import BUCKET_PRIORITY
from ..stock_risk_context import (
    current_bucket_exposure,
    current_sector_exposure,
    sector_from_analysis,
)
from .exposure_service import current_position_snapshot


CAPACITY_POLICY_VERSION = "manager-pre-risk-capacity-v1"
DEFAULT_MIN_INCREMENTAL_VALUE = Decimal("500")


def _env_decimal(name: str, default: str) -> Decimal:
    try:
        return Decimal(str(os.getenv(name, default)))
    except Exception:
        return Decimal(default)


def capacity_policy() -> Dict[str, Any]:
    """Return Manager's pre-risk mirror of Risk_Agent stock limits."""
    return {
        "version": CAPACITY_POLICY_VERSION,
        "max_single_stock_pct": _env_decimal(
            "MAX_SINGLE_STOCK_PCT", "0.10"
        ),
        "max_sector_exposure_pct": _env_decimal(
            "MAX_SECTOR_EXPOSURE_PCT", "0.25"
        ),
        "bucket_limits": {
            "core_dividend": {
                "max_bucket_pct": _env_decimal(
                    "MAX_CORE_DIVIDEND_BUCKET_PCT", "0.50"
                ),
                "max_symbol_pct": _env_decimal(
                    "MAX_CORE_DIVIDEND_SYMBOL_PCT", "0.10"
                ),
            },
            "value_rebound": {
                "max_bucket_pct": _env_decimal(
                    "MAX_VALUE_REBOUND_BUCKET_PCT", "0.30"
                ),
                "max_symbol_pct": _env_decimal(
                    "MAX_VALUE_REBOUND_SYMBOL_PCT", "0.07"
                ),
            },
            "news_momentum": {
                "max_bucket_pct": _env_decimal(
                    "MAX_NEWS_MOMENTUM_BUCKET_PCT", "0.20"
                ),
                "max_symbol_pct": _env_decimal(
                    "MAX_NEWS_MOMENTUM_SYMBOL_PCT", "0.03"
                ),
            },
        },
    }


def _get(record: Any, *names: str, default: Any = None) -> Any:
    if record is None:
        return default
    if isinstance(record, Mapping):
        for name in names:
            value = record.get(name)
            if value is not None:
                return value
        return default
    for name in names:
        value = getattr(record, name, None)
        if value is not None:
            return value
    if hasattr(record, "model_dump"):
        dumped = record.model_dump(mode="json")
        if isinstance(dumped, Mapping):
            return _get(dumped, *names, default=default)
    return default


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None or value == "":
            return default
        return Decimal(str(value))
    except Exception:
        return default


def _positive(values: Iterable[Any]) -> list[Decimal]:
    result: list[Decimal] = []
    for value in values:
        number = _decimal(value)
        if number > 0:
            result.append(number)
    return result


def _position_symbol(position: Any) -> str:
    return str(_get(position, "symbol", "ticker", default="") or "").upper()


def _position_exposure(position: Any) -> Decimal:
    market_value = _decimal(
        _get(position, "market_value", "value", default=None)
    )
    if market_value:
        return abs(market_value)
    quantity = _decimal(
        _get(position, "quantity", "qty", "owned_quantity", default=0)
    )
    price = _decimal(
        _get(
            position,
            "current_market_price",
            "current_price",
            "market_price",
            "average_cost",
            "avg_entry_price",
            default=0,
        )
    )
    return abs(quantity * price)


def _current_symbol_exposure(
    positions: Iterable[Any], symbol: str
) -> Decimal:
    symbol = str(symbol or "").upper()
    return sum(
        (
            _position_exposure(position)
            for position in positions or []
            if _position_symbol(position) == symbol
        ),
        Decimal("0"),
    )


def _candidate_meta(
    allocation_plan: Mapping[str, Any], bucket: str, symbol: str
) -> Dict[str, Any]:
    bucket_payload = (
        (allocation_plan.get("buckets") or {}).get(bucket) or {}
    )
    for candidate in bucket_payload.get("candidates") or []:
        if str(candidate.get("symbol") or "").upper() == str(
            symbol or ""
        ).upper():
            return dict(candidate)
    return {}


def _candidate_analysis(
    ranked_by_symbol: Mapping[str, Mapping[str, Any]], symbol: str
) -> Dict[str, Any]:
    item = ranked_by_symbol.get(str(symbol or "").upper()) or {}
    analysis = item.get("analysis") or {}
    if hasattr(analysis, "model_dump"):
        analysis = analysis.model_dump(mode="json")
    return dict(analysis) if isinstance(analysis, Mapping) else {}


def _capacity_reason(
    *,
    current_symbol: Decimal,
    max_symbol: Decimal,
    desired_increment: Decimal,
    remaining_bucket: Decimal,
    remaining_sector: Optional[Decimal],
    allowed_increment: Decimal,
    min_increment: Decimal,
) -> str:
    if current_symbol >= max_symbol:
        return "current_symbol_exposure_at_or_above_limit"
    if desired_increment <= 0:
        return "per_symbol_target_already_met"
    if remaining_bucket <= 0:
        return "bucket_capacity_exhausted"
    if remaining_sector is not None and remaining_sector <= 0:
        return "sector_capacity_exhausted"
    if allowed_increment < min_increment:
        return "remaining_capacity_below_minimum_trade_value"
    return "capacity_not_available"


def _rounded(value: Optional[Decimal]) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), 2)


def _capacity_decision(
    *,
    row: Mapping[str, Any],
    bucket: str,
    allocation_plan: Mapping[str, Any],
    ranked_by_symbol: Mapping[str, Mapping[str, Any]],
    positions: list[Any],
    portfolio_value: Decimal,
    policy: Mapping[str, Any],
    provisional_symbol: Mapping[str, Decimal],
    provisional_bucket: Mapping[str, Decimal],
    provisional_sector: Mapping[str, Decimal],
    min_increment: Decimal,
) -> Dict[str, Any]:
    symbol = str(row.get("symbol") or "").upper()
    analysis = _candidate_analysis(ranked_by_symbol, symbol)
    sector = sector_from_analysis(analysis)
    sector_key = str(sector or "").strip().lower()

    bucket_policy = dict(
        (policy.get("bucket_limits") or {}).get(bucket) or {}
    )
    max_single_stock = portfolio_value * _decimal(
        policy.get("max_single_stock_pct"), Decimal("0.10")
    )
    bucket_max_symbol = portfolio_value * _decimal(
        bucket_policy.get("max_symbol_pct"), Decimal("0")
    )
    max_symbol = (
        min(max_single_stock, bucket_max_symbol)
        if bucket_max_symbol > 0
        else max_single_stock
    )
    max_bucket = portfolio_value * _decimal(
        bucket_policy.get("max_bucket_pct"), Decimal("0")
    )
    max_sector = (
        portfolio_value
        * _decimal(
            policy.get("max_sector_exposure_pct"), Decimal("0.25")
        )
        if sector
        else None
    )

    existing_symbol = _current_symbol_exposure(positions, symbol)
    current_symbol = existing_symbol + provisional_symbol.get(
        symbol, Decimal("0")
    )
    current_bucket = current_bucket_exposure(
        positions,
        bucket,
        inferred_symbol=symbol,
    ) + provisional_bucket.get(bucket, Decimal("0"))
    current_sector = (
        current_sector_exposure(
            positions,
            sector,
            inferred_symbol=symbol,
        )
        + provisional_sector.get(sector_key, Decimal("0"))
        if sector
        else Decimal("0")
    )

    candidate_meta = _candidate_meta(allocation_plan, bucket, symbol)
    bucket_payload = (
        (allocation_plan.get("buckets") or {}).get(bucket) or {}
    )
    target_candidates = _positive(
        (
            row.get("capacity_adjusted_target_value"),
            candidate_meta.get("suggested_equal_weight_value"),
            candidate_meta.get("suggested_max_value"),
            bucket_payload.get("max_symbol_value"),
            max_symbol,
        )
    )
    desired_target = min(target_candidates) if target_candidates else max_symbol
    desired_target = min(desired_target, max_symbol)
    desired_increment = max(Decimal("0"), desired_target - current_symbol)

    remaining_symbol = max(Decimal("0"), max_symbol - current_symbol)
    remaining_bucket = max(Decimal("0"), max_bucket - current_bucket)
    remaining_sector = (
        max(Decimal("0"), max_sector - current_sector)
        if max_sector is not None
        else None
    )
    capacities = [desired_increment, remaining_symbol, remaining_bucket]
    if remaining_sector is not None:
        capacities.append(remaining_sector)
    allowed_increment = max(Decimal("0"), min(capacities))
    accepted = allowed_increment >= min_increment
    target_value = current_symbol + allowed_increment if accepted else None

    reason = (
        "capacity_available"
        if accepted
        else _capacity_reason(
            current_symbol=current_symbol,
            max_symbol=max_symbol,
            desired_increment=desired_increment,
            remaining_bucket=remaining_bucket,
            remaining_sector=remaining_sector,
            allowed_increment=allowed_increment,
            min_increment=min_increment,
        )
    )

    return {
        "accepted": accepted,
        "reason": reason,
        "symbol": symbol,
        "strategy_bucket": bucket,
        "sector": sector,
        "existing_symbol_exposure": _rounded(existing_symbol),
        "current_symbol_exposure": _rounded(current_symbol),
        "current_bucket_exposure": _rounded(current_bucket),
        "current_sector_exposure": _rounded(current_sector),
        "desired_target_value": _rounded(desired_target),
        "desired_incremental_value": _rounded(desired_increment),
        "allowed_incremental_value": _rounded(allowed_increment),
        "capacity_adjusted_target_value": _rounded(target_value),
        "remaining_symbol_capacity": _rounded(remaining_symbol),
        "remaining_bucket_capacity": _rounded(remaining_bucket),
        "remaining_sector_capacity": _rounded(remaining_sector),
        "max_symbol_exposure": _rounded(max_symbol),
        "max_bucket_exposure": _rounded(max_bucket),
        "max_sector_exposure": _rounded(max_sector),
        "minimum_incremental_value": _rounded(min_increment),
        "policy_version": policy.get("version"),
    }


def apply_pre_risk_capacity_selection(
    *,
    ranked: list[Dict[str, Any]],
    allocation_plan: Dict[str, Any],
    bucket_selection: Dict[str, Any],
    positions: Iterable[Any] | None,
    portfolio_value: Any,
    minimum_incremental_value: Any = DEFAULT_MIN_INCREMENTAL_VALUE,
) -> Dict[str, Any]:
    """Re-select candidates using remaining symbol/bucket/sector capacity.

    Candidates that are already over their final symbol cap are removed before
    Risk_Agent is called. Eligible overflow candidates are promoted in score
    order until the original bucket limit is filled.
    """
    policy = capacity_policy()
    portfolio_value = _decimal(portfolio_value)
    min_increment = max(
        Decimal("0"), _decimal(minimum_incremental_value)
    )
    explicit_positions = list(positions or [])
    positions = (
        explicit_positions
        if explicit_positions
        else current_position_snapshot()
    )
    ranked_by_symbol = {
        str(item.get("symbol") or "").upper(): item
        for item in ranked or []
    }
    adjusted = deepcopy(bucket_selection or {})
    provisional_symbol: Dict[str, Decimal] = {}
    provisional_bucket: Dict[str, Decimal] = {}
    provisional_sector: Dict[str, Decimal] = {}
    diagnostics: list[Dict[str, Any]] = []
    skipped: list[Dict[str, Any]] = []
    promoted: list[Dict[str, Any]] = []

    for bucket in BUCKET_PRIORITY:
        payload = dict(adjusted.get(bucket) or {})
        limit = max(0, int(payload.get("limit") or 0))
        original_selected = [
            dict(row) for row in payload.get("selected") or []
        ]
        original_selected_symbols = {
            str(row.get("symbol") or "").upper()
            for row in original_selected
        }
        candidates = [
            *original_selected,
            *[dict(row) for row in payload.get("overflow") or []],
        ]
        accepted_rows: list[Dict[str, Any]] = []
        remaining_rows: list[Dict[str, Any]] = []
        bucket_skips: list[Dict[str, Any]] = []

        for row in candidates:
            if len(accepted_rows) >= limit:
                remaining_rows.append(row)
                continue
            decision = _capacity_decision(
                row=row,
                bucket=bucket,
                allocation_plan=allocation_plan,
                ranked_by_symbol=ranked_by_symbol,
                positions=positions,
                portfolio_value=portfolio_value,
                policy=policy,
                provisional_symbol=provisional_symbol,
                provisional_bucket=provisional_bucket,
                provisional_sector=provisional_sector,
                min_increment=min_increment,
            )
            diagnostics.append(decision)
            next_row = dict(row)
            next_row["pre_risk_capacity"] = decision
            if decision["accepted"]:
                is_promoted = (
                    decision["symbol"] not in original_selected_symbols
                )
                next_row["target_value"] = decision[
                    "capacity_adjusted_target_value"
                ]
                next_row["capacity_adjusted_target_value"] = decision[
                    "capacity_adjusted_target_value"
                ]
                next_row["capacity_incremental_value"] = decision[
                    "allowed_incremental_value"
                ]
                next_row["capacity_policy_version"] = policy["version"]
                next_row["capacity_fallback_promoted"] = is_promoted
                accepted_rows.append(next_row)

                increment = _decimal(
                    decision["allowed_incremental_value"]
                )
                symbol = decision["symbol"]
                provisional_symbol[symbol] = (
                    provisional_symbol.get(symbol, Decimal("0"))
                    + increment
                )
                provisional_bucket[bucket] = (
                    provisional_bucket.get(bucket, Decimal("0"))
                    + increment
                )
                sector_key = str(
                    decision.get("sector") or ""
                ).strip().lower()
                if sector_key:
                    provisional_sector[sector_key] = (
                        provisional_sector.get(
                            sector_key, Decimal("0")
                        )
                        + increment
                    )
                if is_promoted:
                    promoted.append(next_row)
            else:
                skip_row = {
                    **next_row,
                    "capacity_skip_reason": decision["reason"],
                }
                bucket_skips.append(skip_row)
                skipped.append(skip_row)

        payload["selected"] = accepted_rows
        payload["selected_count"] = len(accepted_rows)
        payload["overflow"] = remaining_rows
        payload["capacity_skipped"] = bucket_skips
        payload["capacity_skipped_count"] = len(bucket_skips)
        payload["capacity_promoted_count"] = sum(
            1
            for row in accepted_rows
            if row.get("capacity_fallback_promoted")
        )
        adjusted[bucket] = payload

    summary = dict(adjusted.get("summary") or {})
    summary.update(
        {
            "total_selected_before_capacity": sum(
                len(
                    (bucket_selection.get(bucket) or {}).get(
                        "selected"
                    )
                    or []
                )
                for bucket in BUCKET_PRIORITY
            ),
            "total_selected": sum(
                len((adjusted.get(bucket) or {}).get("selected") or [])
                for bucket in BUCKET_PRIORITY
            ),
            "pre_risk_capacity_policy_version": policy["version"],
            "pre_risk_capacity_skipped_count": len(skipped),
            "pre_risk_capacity_promoted_count": len(promoted),
        }
    )
    adjusted["summary"] = summary

    return {
        "bucket_selection": adjusted,
        "diagnostics": diagnostics,
        "skipped": skipped,
        "promoted": promoted,
        "position_snapshot_count": len(positions),
        "position_snapshot_source": (
            "explicit" if explicit_positions else "request_context"
        ),
        "policy": {
            "version": policy["version"],
            "max_single_stock_pct": float(
                policy["max_single_stock_pct"]
            ),
            "max_sector_exposure_pct": float(
                policy["max_sector_exposure_pct"]
            ),
            "bucket_limits": {
                bucket: {
                    key: float(value)
                    for key, value in limits.items()
                }
                for bucket, limits in policy["bucket_limits"].items()
            },
            "minimum_incremental_value": float(min_increment),
        },
        "summary": {
            "considered_count": len(diagnostics),
            "selected_count": summary["total_selected"],
            "skipped_count": len(skipped),
            "promoted_count": len(promoted),
        },
    }

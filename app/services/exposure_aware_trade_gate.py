from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_DOWN
from typing import Any, Dict, Iterable, List, Mapping, Optional

from ..portfolio_allocation import DEFAULT_BUCKET_POLICIES, UNASSIGNED

ACTIVE_ENTRY_ORDER_STATUSES = {
    "accepted",
    "accepted_for_bidding",
    "calculated",
    "held",
    "new",
    "partially_filled",
    "pending",
    "pending_cancel",
    "pending_new",
    "pending_replace",
    "placed",
    "stopped",
}
VALID_PROTECTION_STATUSES = ACTIVE_ENTRY_ORDER_STATUSES - {"pending_cancel"}
STOP_ORDER_TYPES = {"stop", "stop_limit", "stop_loss", "trailing_stop"}
VALID_BUCKETS = frozenset(DEFAULT_BUCKET_POLICIES)


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value in (None, ""):
            return default
        return Decimal(str(value))
    except Exception:
        return default


def _value(row: Any, *names: str) -> Any:
    if isinstance(row, Mapping):
        for name in names:
            if name in row:
                return row.get(name)
        return None
    for name in names:
        if hasattr(row, name):
            return getattr(row, name)
    if hasattr(row, "model_dump"):
        payload = row.model_dump(mode="json")
        if isinstance(payload, Mapping):
            for name in names:
                if name in payload:
                    return payload.get(name)
    return None


def _symbol(row: Any) -> str:
    return str(_value(row, "symbol", "ticker") or "").strip().upper()


def _bucket(row: Any) -> str:
    direct = str(_value(row, "strategy_bucket", "bucket") or "").strip().lower()
    if direct in VALID_BUCKETS:
        return direct

    if isinstance(row, Mapping):
        for key in (
            "strategy_bucket_classification",
            "score_breakdown",
            "analysis",
            "metadata",
            "scanner_candidate",
        ):
            nested = row.get(key)
            if isinstance(nested, Mapping):
                nested_bucket = str(
                    nested.get("strategy_bucket") or nested.get("bucket") or ""
                ).strip().lower()
                if nested_bucket in VALID_BUCKETS:
                    return nested_bucket
    return UNASSIGNED


def _quantity(row: Any) -> Decimal:
    return abs(_decimal(_value(row, "quantity", "qty", "final_quantity")))


def _price(row: Any) -> Decimal:
    return _decimal(
        _value(
            row,
            "current_market_price",
            "current_price",
            "market_price",
            "average_cost",
            "avg_entry_price",
            "avg_execution_price",
            "limit_price",
            "stop_price",
            "price",
        )
    )


def _position_exposure(row: Any) -> Decimal:
    market_value = abs(_decimal(_value(row, "market_value", "exposure")))
    if market_value > 0:
        return market_value
    return _quantity(row) * _price(row)


def _status(row: Any) -> str:
    return str(_value(row, "broker_status", "status") or "").strip().lower()


def _side(row: Any) -> str:
    return str(_value(row, "side") or "").strip().lower()


def _order_type(row: Any) -> str:
    return str(_value(row, "order_type", "type") or "").strip().lower()


def _is_active_entry_order(row: Any) -> bool:
    status = _status(row)
    return not status or status in ACTIVE_ENTRY_ORDER_STATUSES


def _order_exposure(row: Any) -> Decimal:
    notional = abs(_decimal(_value(row, "notional")))
    if notional > 0:
        return notional
    return _quantity(row) * _price(row)


def _flatten_orders(orders: Iterable[Any]) -> List[Any]:
    flattened: List[Any] = []
    for order in orders or []:
        flattened.append(order)
        legs = _value(order, "legs") or []
        if isinstance(legs, list):
            flattened.extend(_flatten_orders(legs))
    return flattened


def _has_stop_trigger(row: Any) -> bool:
    if _order_type(row) == "trailing_stop":
        return bool(
            _value(row, "trail_price", "trail_percent")
            not in (None, "", 0, "0", "0.0", "0.00")
        )
    return bool(
        _value(row, "stop_price", "trigger_price")
        not in (None, "", 0, "0", "0.0", "0.00")
    )


def _is_valid_protective_stop(row: Any) -> bool:
    status = _status(row)
    return (
        _side(row) == "sell"
        and _order_type(row) in STOP_ORDER_TYPES
        and (not status or status in VALID_PROTECTION_STATUSES)
        and _has_stop_trigger(row)
    )


def _policy_decimal(policy: Any, name: str) -> Decimal:
    value = getattr(policy, name, None) if not isinstance(policy, Mapping) else policy.get(name)
    return _decimal(value)


def _money(value: Decimal) -> float:
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_DOWN))


def build_exposure_snapshot(
    *,
    portfolio_value: Decimal,
    positions: List[Any],
    open_orders: List[Any],
    policies: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Build one normalized view of held, pending, bucket, and protection exposure."""
    policy_map = policies or DEFAULT_BUCKET_POLICIES
    portfolio_value = max(Decimal("0"), _decimal(portfolio_value))

    bucket_position_exposure: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    bucket_pending_buy_exposure: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    symbol_position_exposure: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    symbol_pending_buy_exposure: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    position_qty: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))

    for position in positions or []:
        symbol = _symbol(position)
        if not symbol:
            continue
        bucket = _bucket(position)
        exposure = _position_exposure(position)
        bucket_position_exposure[bucket] += exposure
        symbol_position_exposure[symbol] += exposure
        position_qty[symbol] += _quantity(position)

    flattened_orders = _flatten_orders(open_orders or [])
    stop_covered_qty: Dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for order in flattened_orders:
        symbol = _symbol(order)
        if not symbol:
            continue
        if _side(order) == "buy" and _is_active_entry_order(order):
            bucket = _bucket(order)
            exposure = _order_exposure(order)
            bucket_pending_buy_exposure[bucket] += exposure
            symbol_pending_buy_exposure[symbol] += exposure
        if _is_valid_protective_stop(order):
            stop_covered_qty[symbol] += _quantity(order)

    unprotected_positions = []
    protection_by_symbol: Dict[str, Dict[str, Any]] = {}
    for symbol, qty in sorted(position_qty.items()):
        covered = stop_covered_qty.get(symbol, Decimal("0"))
        missing = max(Decimal("0"), qty - covered)
        is_fully_protected = qty > 0 and missing == 0
        protection_by_symbol[symbol] = {
            "position_qty": float(qty),
            "stop_covered_qty": float(covered),
            "unprotected_stop_qty": float(missing),
            "fully_stop_protected": is_fully_protected,
        }
        if not is_fully_protected:
            unprotected_positions.append(symbol)

    buckets: Dict[str, Dict[str, Any]] = {}
    all_buckets = set(policy_map) | set(bucket_position_exposure) | set(bucket_pending_buy_exposure)
    for bucket in sorted(all_buckets):
        policy = policy_map.get(bucket)
        target_weight = _policy_decimal(policy, "target_weight") if policy else Decimal("0")
        target_value = portfolio_value * target_weight
        held = bucket_position_exposure.get(bucket, Decimal("0"))
        pending = bucket_pending_buy_exposure.get(bucket, Decimal("0"))
        committed = held + pending
        buckets[bucket] = {
            "target_weight": float(target_weight),
            "target_value": _money(target_value),
            "position_exposure": _money(held),
            "pending_buy_exposure": _money(pending),
            "committed_exposure": _money(committed),
            "remaining_capacity": _money(max(Decimal("0"), target_value - committed)),
            "overweight_value": _money(max(Decimal("0"), committed - target_value)),
        }

    return {
        "portfolio_value": _money(portfolio_value),
        "buckets": buckets,
        "symbol_position_exposure": {
            symbol: _money(value) for symbol, value in sorted(symbol_position_exposure.items())
        },
        "symbol_pending_buy_exposure": {
            symbol: _money(value) for symbol, value in sorted(symbol_pending_buy_exposure.items())
        },
        "protection_by_symbol": protection_by_symbol,
        "unprotected_positions": unprotected_positions,
        "summary": {
            "position_count": len(positions or []),
            "broker_order_count": len(open_orders or []),
            "flattened_order_count": len(flattened_orders),
            "unprotected_position_count": len(unprotected_positions),
        },
    }


_ACTION_BY_CODE = {
    "database_sync_unhealthy": "reconcile_database_and_broker_before_new_entries",
    "broker_snapshot_stale": "refresh_broker_snapshot_before_new_entries",
    "existing_positions_not_fully_protected": "reconcile_protective_orders_before_new_entries",
    "strategy_bucket_unassigned": "classify_strategy_bucket_before_risk_review",
    "bucket_capacity_exhausted": "reduce_bucket_exposure_or_wait_for_capacity",
    "symbol_capacity_exhausted": "reduce_symbol_exposure_or_wait_for_capacity",
    "portfolio_value_unavailable": "refresh_account_balance_and_position_values",
}


def evaluate_exposure_aware_trade_gate(
    candidate: Mapping[str, Any],
    *,
    portfolio_value: Decimal,
    positions: List[Any],
    open_orders: List[Any],
    policies: Optional[Mapping[str, Any]] = None,
    database_sync_ok: bool = True,
    snapshot_age_seconds: Optional[float] = None,
    max_snapshot_age_seconds: float = 60.0,
    block_on_unprotected_positions: bool = True,
    exposure_snapshot: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Fail closed when portfolio capacity or operational safety is not verifiable."""
    policy_map = policies or DEFAULT_BUCKET_POLICIES
    snapshot = exposure_snapshot or build_exposure_snapshot(
        portfolio_value=portfolio_value,
        positions=positions,
        open_orders=open_orders,
        policies=policy_map,
    )
    symbol = _symbol(candidate)
    bucket = _bucket(candidate)
    rejection_codes: List[str] = []

    if _decimal(portfolio_value) <= 0:
        rejection_codes.append("portfolio_value_unavailable")
    if not database_sync_ok:
        rejection_codes.append("database_sync_unhealthy")
    if snapshot_age_seconds is not None and float(snapshot_age_seconds) > float(max_snapshot_age_seconds):
        rejection_codes.append("broker_snapshot_stale")
    if block_on_unprotected_positions and snapshot.get("unprotected_positions"):
        rejection_codes.append("existing_positions_not_fully_protected")
    if bucket not in policy_map:
        rejection_codes.append("strategy_bucket_unassigned")

    bucket_row = (snapshot.get("buckets") or {}).get(bucket) or {}
    bucket_capacity = _decimal(bucket_row.get("remaining_capacity"))
    policy = policy_map.get(bucket)
    max_symbol_weight = _policy_decimal(policy, "max_symbol_weight") if policy else Decimal("0")
    symbol_limit = max(Decimal("0"), _decimal(portfolio_value) * max_symbol_weight)
    symbol_committed = _decimal(
        (snapshot.get("symbol_position_exposure") or {}).get(symbol)
    ) + _decimal((snapshot.get("symbol_pending_buy_exposure") or {}).get(symbol))
    symbol_capacity = max(Decimal("0"), symbol_limit - symbol_committed)

    if bucket in policy_map and bucket_capacity <= 0:
        rejection_codes.append("bucket_capacity_exhausted")
    if bucket in policy_map and symbol_capacity <= 0:
        rejection_codes.append("symbol_capacity_exhausted")

    maximum_order_value = max(
        Decimal("0"),
        min(bucket_capacity, symbol_capacity) if bucket in policy_map else Decimal("0"),
    )
    rejection_codes = list(dict.fromkeys(rejection_codes))
    required_actions = list(
        dict.fromkeys(
            _ACTION_BY_CODE[code]
            for code in rejection_codes
            if code in _ACTION_BY_CODE
        )
    )

    return {
        "allowed": not rejection_codes and maximum_order_value > 0,
        "symbol": symbol,
        "strategy_bucket": bucket,
        "maximum_order_value": _money(maximum_order_value),
        "bucket_remaining_capacity": _money(bucket_capacity),
        "symbol_remaining_capacity": _money(symbol_capacity),
        "symbol_committed_exposure": _money(symbol_committed),
        "rejection_codes": rejection_codes,
        "required_actions": required_actions,
        "blocking_unprotected_symbols": list(snapshot.get("unprotected_positions") or []),
        "database_sync_ok": bool(database_sync_ok),
        "snapshot_age_seconds": snapshot_age_seconds,
        "max_snapshot_age_seconds": max_snapshot_age_seconds,
    }


def filter_candidates_with_exposure_gate(
    *,
    selected_positions: List[Dict[str, Any]],
    position_analysis_payloads: List[Dict[str, Any]],
    portfolio_value: Decimal,
    positions: List[Any],
    open_orders: List[Any],
    policies: Optional[Mapping[str, Any]] = None,
    database_sync_ok: bool = True,
    snapshot_age_seconds: Optional[float] = None,
    max_snapshot_age_seconds: float = 60.0,
    block_on_unprotected_positions: bool = True,
) -> Dict[str, Any]:
    """Filter selected candidates and preserve an auditable gate decision per symbol."""
    snapshot = build_exposure_snapshot(
        portfolio_value=portfolio_value,
        positions=positions,
        open_orders=open_orders,
        policies=policies,
    )
    payload_by_symbol = {
        _symbol(payload): payload
        for payload in position_analysis_payloads or []
        if _symbol(payload)
    }

    allowed_positions: List[Dict[str, Any]] = []
    allowed_payloads: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    decisions: List[Dict[str, Any]] = []

    for candidate in selected_positions or []:
        gate = evaluate_exposure_aware_trade_gate(
            candidate,
            portfolio_value=portfolio_value,
            positions=positions,
            open_orders=open_orders,
            policies=policies,
            database_sync_ok=database_sync_ok,
            snapshot_age_seconds=snapshot_age_seconds,
            max_snapshot_age_seconds=max_snapshot_age_seconds,
            block_on_unprotected_positions=block_on_unprotected_positions,
            exposure_snapshot=snapshot,
        )
        decisions.append(gate)
        symbol = gate["symbol"]
        enriched = dict(candidate)
        enriched["exposure_gate"] = gate
        enriched["maximum_order_value"] = gate["maximum_order_value"]
        if gate["allowed"]:
            allowed_positions.append(enriched)
            payload = payload_by_symbol.get(symbol)
            if payload is not None:
                next_payload = dict(payload)
                next_payload["exposure_gate"] = gate
                next_payload["maximum_order_value"] = gate["maximum_order_value"]
                allowed_payloads.append(next_payload)
        else:
            rejected.append(
                {
                    "symbol": symbol,
                    "strategy_bucket": gate["strategy_bucket"],
                    "status": "blocked_by_exposure_gate",
                    "rejection_codes": gate["rejection_codes"],
                    "required_actions": gate["required_actions"],
                    "maximum_order_value": gate["maximum_order_value"],
                }
            )

    return {
        "selected_positions": allowed_positions,
        "position_analysis_payloads": allowed_payloads,
        "rejected": rejected,
        "decisions": decisions,
        "exposure_snapshot": snapshot,
        "summary": {
            "candidate_count": len(selected_positions or []),
            "allowed_count": len(allowed_positions),
            "rejected_count": len(rejected),
            "global_new_entry_blocked": bool(
                block_on_unprotected_positions and snapshot.get("unprotected_positions")
            ),
        },
    }

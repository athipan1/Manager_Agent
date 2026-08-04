"""Paper-only promotion observation and broker/database reconciliation.

Manager_Agent orchestrates the check, Execution_Agent remains the only broker
boundary, and Database_Agent remains the promotion source of truth. A candidate
cannot reach Risk_Agent when its observation is missing, stale, malformed, or
terminal.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel

from .. import config
from ..execution_client import ExecutionAgentClient
from .promotion_database_adapter import PromotionDatabaseAdapter


_ACTIVE_ORDER_STATUSES = {
    "accepted",
    "held",
    "new",
    "open",
    "partially_filled",
    "pending_cancel",
    "pending_new",
    "pending_replace",
    "submitted",
}
_APPROVED_OBSERVATION_STATE = "PAPER_OBSERVING"


class PromotionObservationError(RuntimeError):
    pass


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if hasattr(value, "model_dump"):
        result = value.model_dump(mode="json")
        return result if isinstance(result, dict) else {}
    if hasattr(value, "dict"):
        result = value.dict()
        return result if isinstance(result, dict) else {}
    return {}


def _rows(value: Any) -> List[Dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, dict):
        for key in ("items", "orders", "positions", "data"):
            nested = value.get(key)
            if isinstance(nested, list):
                return [_as_dict(row) for row in nested]
        return [_as_dict(value)]
    if isinstance(value, (list, tuple)):
        return [_as_dict(row) for row in value]
    return [_as_dict(value)]


def _symbol(value: Any) -> str:
    row = _as_dict(value)
    return str(row.get("symbol") or row.get("ticker") or "").upper()


def _status(value: Any) -> str:
    row = _as_dict(value)
    return str(row.get("status") or row.get("order_status") or "").lower()


def _active_orders(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result = []
    for row in rows:
        status = _status(row)
        if not status or status in _ACTIVE_ORDER_STATUSES:
            result.append(row)
    return result


def _order_identity(row: Dict[str, Any]) -> str:
    for key in (
        "broker_order_id",
        "order_id",
        "id",
        "client_order_id",
        "trade_id",
    ):
        value = row.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _identity_set(rows: Iterable[Dict[str, Any]]) -> tuple[set[str], int]:
    identities: set[str] = set()
    missing = 0
    for row in rows:
        identity = _order_identity(row)
        if identity:
            identities.add(identity)
        else:
            missing += 1
    return identities, missing


def _duplicate_count(rows: Iterable[Dict[str, Any]]) -> int:
    seen: set[str] = set()
    duplicates = 0
    for row in rows:
        identity = _order_identity(row)
        if not identity:
            continue
        if identity in seen:
            duplicates += 1
        else:
            seen.add(identity)
    return duplicates


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _iso_timestamp(value: Any) -> str:
    parsed = _parse_timestamp(value) or datetime.now(timezone.utc)
    return parsed.isoformat().replace("+00:00", "Z")


def _float(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    if result != result or result in {float("inf"), float("-inf")}:
        return 0.0
    return result


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return result if result.is_finite() else None


def _paper_drawdown_pct(
    symbol: str,
    broker_positions: Iterable[Dict[str, Any]],
) -> float:
    matching = [row for row in broker_positions if _symbol(row) == symbol]
    if not matching:
        return 0.0
    worst = 0.0
    for row in matching:
        unrealized_pl = _float(
            row.get("unrealized_pl")
            or row.get("unrealized_pnl")
            or row.get("unrealized_profit_loss")
        )
        denominator = abs(
            _float(row.get("cost_basis"))
            or _float(row.get("market_value"))
            or (_float(row.get("avg_entry_price")) * abs(_float(row.get("qty"))))
        )
        if unrealized_pl < 0 and denominator > 0:
            worst = max(worst, min(1.0, abs(unrealized_pl) / denominator))
    return worst


def _strategy_drift(
    decision: Dict[str, Any],
    payloads: Iterable[Dict[str, Any]],
) -> bool:
    expected = str(
        decision.get("selected_strategy_id")
        or decision.get("strategy_id")
        or ""
    )
    if not expected:
        return True
    symbol = str(decision.get("symbol") or "").upper()
    explicit = {
        str(
            row.get("selected_strategy_id")
            or row.get("strategy_id")
            or ""
        )
        for row in payloads
        if _symbol(row) == symbol
        and (
            row.get("selected_strategy_id") is not None
            or row.get("strategy_id") is not None
        )
    }
    return bool(explicit and explicit != {expected})


def _observation_key(
    *,
    account_id: str,
    promotion_id: str,
    correlation_id: str,
) -> str:
    digest = hashlib.sha256(
        f"{account_id}\x1f{promotion_id}\x1f{correlation_id}".encode("utf-8")
    ).hexdigest()
    return f"manager-paper-observation:{digest}"


def _reconciliation_payload(response: Any) -> Dict[str, Any]:
    standard = _as_dict(response)
    raw_data = standard.get("data")
    data: Dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    if not data and hasattr(response, "data"):
        data = _as_dict(getattr(response, "data"))
    return dict(data)


def _validate_reconciliation_contract(
    reconciliation: Dict[str, Any],
) -> tuple[Dict[str, Any], Optional[datetime], Optional[str]]:
    errors: List[str] = []
    reconciled_at = _parse_timestamp(reconciliation.get("reconciled_at"))
    if reconciled_at is None:
        errors.append("reconciliation_timestamp_missing_or_invalid")

    raw_broker_state = reconciliation.get("broker_state")
    broker_state: Dict[str, Any] = (
        dict(raw_broker_state) if isinstance(raw_broker_state, dict) else {}
    )
    if not broker_state:
        errors.append("broker_state_missing_or_invalid")
    else:
        if _parse_timestamp(broker_state.get("captured_at")) is None:
            errors.append("broker_state_timestamp_missing_or_invalid")
        if not isinstance(broker_state.get("open_orders"), list):
            errors.append("broker_open_orders_missing_or_invalid")
        if not isinstance(broker_state.get("positions"), list):
            errors.append("broker_positions_missing_or_invalid")

    raw_database_sync = reconciliation.get("database_sync")
    database_sync = (
        raw_database_sync if isinstance(raw_database_sync, dict) else {}
    )
    if database_sync.get("status") != "success":
        errors.append("broker_database_sync_not_successful")
    if reconciliation.get("ok") is not True:
        errors.append("broker_reconciliation_not_ok")

    return broker_state, reconciled_at, ";".join(errors) or None


def _order_reconciliation(
    *,
    reconciliation_ok: bool,
    broker_orders: List[Dict[str, Any]],
    database_orders: List[Dict[str, Any]],
    symbol: Optional[str] = None,
) -> Dict[str, Any]:
    if symbol is None:
        broker = list(broker_orders)
        database = list(database_orders)
    else:
        broker = [row for row in broker_orders if _symbol(row) == symbol]
        database = [row for row in database_orders if _symbol(row) == symbol]
    broker_ids, broker_missing = _identity_set(broker)
    database_ids, database_missing = _identity_set(database)
    duplicates = _duplicate_count(broker) + _duplicate_count(database)
    missing_symbols = (
        sum(1 for row in broker if not _symbol(row))
        + sum(1 for row in database if not _symbol(row))
        if symbol is None
        else 0
    )
    exact_identity_match = (
        broker_missing == 0
        and database_missing == 0
        and missing_symbols == 0
        and broker_ids == database_ids
        and len(broker) == len(database)
    )
    return {
        "reconciliation_ok": bool(
            reconciliation_ok
            and duplicates == 0
            and exact_identity_match
        ),
        "duplicate_order_count": duplicates,
        "broker_order_count": len(broker),
        "database_order_count": len(database),
        "filled_order_count": 0,
        "broker_identity_count": len(broker_ids),
        "database_identity_count": len(database_ids),
        "broker_missing_identity_count": broker_missing,
        "database_missing_identity_count": database_missing,
        "order_missing_symbol_count": missing_symbols,
    }


def _reconciliation_for_symbol(
    *,
    symbol: str,
    reconciliation_ok: bool,
    broker_orders: List[Dict[str, Any]],
    database_orders: List[Dict[str, Any]],
) -> Dict[str, Any]:
    return _order_reconciliation(
        reconciliation_ok=reconciliation_ok,
        broker_orders=broker_orders,
        database_orders=database_orders,
        symbol=symbol,
    )


def _position_quantity(row: Dict[str, Any]) -> Optional[Decimal]:
    return _decimal(
        row.get("quantity")
        if row.get("quantity") is not None
        else row.get("qty")
    )


def _position_totals(
    rows: Iterable[Dict[str, Any]],
    *,
    symbol: Optional[str] = None,
) -> tuple[Dict[str, Decimal], int]:
    totals: Dict[str, Decimal] = {}
    invalid = 0
    for row in rows:
        row_symbol = _symbol(row)
        if symbol is not None and row_symbol != symbol:
            continue
        quantity = _position_quantity(row)
        if not row_symbol or quantity is None:
            invalid += 1
            continue
        totals[row_symbol] = totals.get(row_symbol, Decimal("0")) + quantity
    return totals, invalid


def _position_reconciliation(
    *,
    reconciliation_ok: bool,
    broker_positions: List[Dict[str, Any]],
    database_positions: List[Dict[str, Any]],
    symbol: Optional[str] = None,
) -> Dict[str, Any]:
    broker_totals, broker_invalid = _position_totals(
        broker_positions,
        symbol=symbol,
    )
    database_totals, database_invalid = _position_totals(
        database_positions,
        symbol=symbol,
    )
    mismatched_symbols = sorted(
        candidate
        for candidate in set(broker_totals) | set(database_totals)
        if broker_totals.get(candidate, Decimal("0"))
        != database_totals.get(candidate, Decimal("0"))
    )
    return {
        "reconciliation_ok": bool(
            reconciliation_ok
            and broker_invalid == 0
            and database_invalid == 0
            and not mismatched_symbols
        ),
        "broker_position_count": len(broker_totals),
        "database_position_count": len(database_totals),
        "broker_invalid_position_count": broker_invalid,
        "database_invalid_position_count": database_invalid,
        "position_mismatch_count": len(mismatched_symbols),
        "position_mismatched_symbols": mismatched_symbols,
        "broker_position_quantities": {
            key: str(value) for key, value in broker_totals.items()
        },
        "database_position_quantities": {
            key: str(value) for key, value in database_totals.items()
        },
    }


def _enrich_rows(
    rows: Iterable[Dict[str, Any]],
    observations_by_symbol: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    enriched = []
    for value in rows:
        row = dict(value)
        observation = observations_by_symbol.get(_symbol(row))
        if observation:
            row["promotion_id"] = observation.get("promotion_id")
            row["promotion_observation_id"] = observation.get("observation_id")
            row["promotion_observation_key"] = observation.get("observation_key")
            row["promotion_state"] = observation.get("to_state")
            row["promotion_version"] = observation.get("to_version")
            row["paper_observation"] = observation
        enriched.append(row)
    return enriched


def _merge_reconciliation_error(
    current: Optional[str],
    additional: Optional[str],
) -> Optional[str]:
    values = [value for value in (current, additional) if value]
    return ";".join(values) or None


async def observe_promotion_gate_result(
    *,
    db_client: Any,
    gate_result: Dict[str, Any],
    account_id: str,
    correlation_id: str,
    execution_client: Any = None,
) -> Dict[str, Any]:
    """Observe every promotion-authorized candidate before Risk evaluation."""

    if config.TRADING_MODE != "PAPER" or config.ALLOW_LIVE_TRADING:
        raise PromotionObservationError(
            "paper promotion observation requires TRADING_MODE=PAPER and "
            "ALLOW_LIVE_TRADING=false"
        )

    decisions = [dict(row) for row in gate_result.get("decisions") or []]
    eligible = [row for row in decisions if row.get("allowed")]
    if not eligible:
        return {
            **gate_result,
            "paper_observation": {
                "status": "not_required",
                "required": True,
                "reason": "no_promotion_authorized_candidates",
                "decisions": [],
                "summary": {
                    "candidate_count": 0,
                    "allowed_count": 0,
                    "rejected_count": 0,
                },
            },
        }

    reconciliation: Dict[str, Any] = {}
    reconciliation_error: Optional[str] = None
    owns_client = execution_client is None
    client = execution_client
    try:
        if owns_client:
            client = ExecutionAgentClient()
            await client.__aenter__()
        reconciliation_response = await client.reconcile_broker_state(
            account_id,
            correlation_id,
            push_to_database=True,
        )
        reconciliation = _reconciliation_payload(reconciliation_response)
    except Exception as exc:
        reconciliation = {}
        reconciliation_error = str(exc)
    finally:
        if owns_client and client is not None:
            await client.__aexit__(None, None, None)

    broker_state, reconciled_at, contract_error = (
        _validate_reconciliation_contract(reconciliation)
    )
    reconciliation_error = _merge_reconciliation_error(
        reconciliation_error,
        contract_error,
    )
    broker_orders = _active_orders(_rows(broker_state.get("open_orders")))
    broker_positions = _rows(broker_state.get("positions"))
    contract_ok = reconciliation_error is None
    adapter = PromotionDatabaseAdapter(db_client)

    try:
        database_orders = _active_orders(
            await adapter.get_account_orders_for_reconciliation(
                account_id=account_id,
                correlation_id=correlation_id,
            )
        )
    except Exception as exc:
        database_orders = []
        reconciliation_error = _merge_reconciliation_error(
            reconciliation_error,
            str(exc),
        )

    try:
        database_positions = (
            await adapter.get_account_positions_for_reconciliation(
                account_id=account_id,
                correlation_id=correlation_id,
            )
        )
    except Exception as exc:
        database_positions = []
        reconciliation_error = _merge_reconciliation_error(
            reconciliation_error,
            str(exc),
        )

    account_order_reconciliation = _order_reconciliation(
        reconciliation_ok=contract_ok and reconciliation_error is None,
        broker_orders=broker_orders,
        database_orders=database_orders,
    )
    account_position_reconciliation = _position_reconciliation(
        reconciliation_ok=contract_ok and reconciliation_error is None,
        broker_positions=broker_positions,
        database_positions=database_positions,
    )
    reconciliation_ok = bool(
        account_order_reconciliation["reconciliation_ok"]
        and account_position_reconciliation["reconciliation_ok"]
    )

    observed_at = _iso_timestamp(reconciled_at)
    payloads = [dict(row) for row in gate_result.get("position_analysis_payloads") or []]
    observation_decisions: List[Dict[str, Any]] = []
    observations_by_symbol: Dict[str, Dict[str, Any]] = {}

    for decision in decisions:
        if not decision.get("allowed"):
            observation_decisions.append(decision)
            continue

        symbol = str(decision.get("symbol") or "").upper()
        promotion_id = str(decision.get("promotion_id") or "")
        expected_state = str(decision.get("promotion_state") or "")
        expected_version = decision.get("promotion_version")
        order_metrics = _reconciliation_for_symbol(
            symbol=symbol,
            reconciliation_ok=reconciliation_ok,
            broker_orders=broker_orders,
            database_orders=database_orders,
        )
        position_metrics = _position_reconciliation(
            reconciliation_ok=reconciliation_ok,
            broker_positions=broker_positions,
            database_positions=database_positions,
            symbol=symbol,
        )
        metrics = {
            **order_metrics,
            "position_reconciliation_ok": position_metrics["reconciliation_ok"],
            "broker_position_count": position_metrics["broker_position_count"],
            "database_position_count": position_metrics[
                "database_position_count"
            ],
            "position_mismatch_count": position_metrics[
                "position_mismatch_count"
            ],
            "position_mismatched_symbols": position_metrics[
                "position_mismatched_symbols"
            ],
            "broker_position_quantities": position_metrics[
                "broker_position_quantities"
            ],
            "database_position_quantities": position_metrics[
                "database_position_quantities"
            ],
        }
        metrics["reconciliation_ok"] = bool(
            reconciliation_ok
            and order_metrics["reconciliation_ok"]
            and position_metrics["reconciliation_ok"]
        )
        observation_key = _observation_key(
            account_id=account_id,
            promotion_id=promotion_id,
            correlation_id=correlation_id,
        )
        rejection_codes: List[str] = []
        observation: Dict[str, Any] = {}

        if not symbol or not promotion_id or not isinstance(expected_version, int):
            rejection_codes.append("paper_observation_promotion_identity_invalid")
        elif expected_state not in {"APPROVED_FOR_PAPER", "PAPER_OBSERVING"}:
            rejection_codes.append("paper_observation_state_invalid")
        else:
            try:
                observation = await adapter.observe_for_paper(
                    promotion_id=promotion_id,
                    expected_state=expected_state,
                    expected_version=expected_version,
                    observation_key=observation_key,
                    observed_at=observed_at,
                    paper_drawdown_pct=_paper_drawdown_pct(
                        symbol,
                        broker_positions,
                    ),
                    reconciliation_ok=metrics["reconciliation_ok"],
                    duplicate_order_count=metrics["duplicate_order_count"],
                    broker_order_count=metrics["broker_order_count"],
                    database_order_count=metrics["database_order_count"],
                    filled_order_count=metrics["filled_order_count"],
                    strategy_drift=_strategy_drift(decision, payloads),
                    emergency_halt=bool(config.MANAGER_EMERGENCY_HALT),
                    correlation_id=correlation_id,
                    notes=[
                        "Manager reconciled Database order and position state "
                        "against Execution_Agent broker truth before Risk "
                        "evaluation."
                    ],
                    metadata={
                        "symbol": symbol,
                        "account_id": account_id,
                        "reconciliation_error": reconciliation_error,
                        "account_order_reconciliation": (
                            account_order_reconciliation
                        ),
                        "account_position_reconciliation": (
                            account_position_reconciliation
                        ),
                        **metrics,
                    },
                )
            except Exception as exc:
                rejection_codes.append("paper_observation_write_failed")
                observation = {"error": str(exc)}

        if observation.get("to_state") != _APPROVED_OBSERVATION_STATE:
            rejection_codes.append(
                "paper_observation_terminal"
                if observation.get("to_state") in {"EXPIRED", "REVOKED"}
                else "paper_observation_not_authorized"
            )
        if not metrics["reconciliation_ok"]:
            rejection_codes.append("paper_observation_reconciliation_failed")

        allowed = not rejection_codes
        updated = {
            **decision,
            "allowed": allowed,
            "rejection_codes": sorted(set(rejection_codes)),
            "paper_observation": observation,
            "paper_reconciliation": metrics,
            "observation_key": observation_key,
        }
        observation_decisions.append(updated)
        if allowed:
            observations_by_symbol[symbol] = observation

    allowed_symbols = {
        str(row.get("symbol") or "").upper()
        for row in observation_decisions
        if row.get("allowed")
    }
    selected_positions = [
        row
        for row in gate_result.get("selected_positions") or []
        if _symbol(row) in allowed_symbols
    ]
    selected_payloads = [
        row
        for row in gate_result.get("position_analysis_payloads") or []
        if _symbol(row) in allowed_symbols
    ]
    rejected = [row for row in observation_decisions if not row.get("allowed")]

    return {
        **gate_result,
        "selected_positions": _enrich_rows(
            selected_positions,
            observations_by_symbol,
        ),
        "position_analysis_payloads": _enrich_rows(
            selected_payloads,
            observations_by_symbol,
        ),
        "decisions": observation_decisions,
        "rejected": rejected,
        "paper_observation": {
            "status": "completed",
            "required": True,
            "account_id": account_id,
            "correlation_id": correlation_id,
            "reconciliation_ok": reconciliation_ok,
            "reconciliation_error": reconciliation_error,
            "broker_order_count": len(broker_orders),
            "database_order_count": len(database_orders),
            "broker_position_count": len(broker_positions),
            "database_position_count": len(database_positions),
            "account_order_reconciliation": account_order_reconciliation,
            "account_position_reconciliation": (
                account_position_reconciliation
            ),
            "decisions": observation_decisions,
            "summary": {
                "candidate_count": len(observation_decisions),
                "allowed_count": len(observation_decisions) - len(rejected),
                "rejected_count": len(rejected),
            },
        },
        "summary": {
            **(gate_result.get("summary") or {}),
            "allowed_count": len(observation_decisions) - len(rejected),
            "rejected_count": len(rejected),
            "paper_observation_required": True,
        },
    }

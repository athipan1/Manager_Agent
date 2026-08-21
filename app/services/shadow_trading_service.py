from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from pydantic import BaseModel, ConfigDict, Field


SHADOW_TRADE_SCHEMA_VERSION = "manager-shadow-trade.v2"
RESEARCH_MIN_OPPORTUNITY_SCORE = 0.50
DEFAULT_SHADOW_MAX_MARKS = 6
DEFAULT_SHADOW_COST_BUFFER_BPS = 2.0


def _to_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _profile(candidate: Dict[str, Any]) -> Dict[str, Any]:
    """Read either a Scanner candidate bundle or Manager opportunity-review row."""

    if isinstance(candidate.get("execution_context"), dict) and candidate.get(
        "opportunity_score"
    ) is not None:
        return {
            "schema_version": candidate.get("schema_version"),
            "status": candidate.get("status"),
            "workflow_status": candidate.get("workflow_status"),
            "opportunity_score": candidate.get("opportunity_score"),
            "preferred_strategy_hint": candidate.get("preferred_strategy_hint"),
            "strategy_affinity": candidate.get("strategy_affinity") or {},
            "execution_context": candidate.get("execution_context") or {},
            "evidence_quality": candidate.get("evidence_quality") or {},
            "fail_closed": candidate.get("reason_code")
            == "SCANNER_OPPORTUNITY_FAIL_CLOSED",
        }

    metadata = _to_dict(candidate.get("metadata"))
    details = _to_dict(metadata.get("details"))
    bundle = _to_dict(details.get("data_bundle")) or _to_dict(
        metadata.get("data_bundle")
    )
    return _to_dict(bundle.get("opportunity_profile"))


def _score(candidate: Dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = candidate.get(key)
        if value is None:
            continue
        number = _finite(value)
        if number is not None:
            return number / 100.0 if number > 1.0 else number
    return None


def _candidate_symbol(candidate: Dict[str, Any]) -> str:
    return str(candidate.get("symbol") or candidate.get("ticker") or "").strip().upper()


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value or "").strip()
        if not raw:
            return None
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


class ShadowPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: int | str
    candidate: Dict[str, Any]
    correlation_id: str = Field(min_length=1, max_length=200)
    strategy_version: str | None = Field(default=None, max_length=200)
    source_commit_sha: str | None = Field(default=None, max_length=80)


class ShadowTradePlan(BaseModel):
    schema_version: str = SHADOW_TRADE_SCHEMA_VERSION
    shadow_trade_id: str
    signal_id: str
    account_id: int | str
    correlation_id: str
    symbol: str
    side: str = "buy"
    strategy_id: str
    strategy_version: str | None = None
    event_type: str = "signal_decision"
    decision_price: float
    bid: float | None = None
    ask: float | None = None
    spread_bps: float | None = None
    simulated_fill_price: float
    simulated_slippage_bps: float
    scanner_score: float | None = None
    opportunity_score: float
    market_regime: str | None = None
    source_commit_sha: str | None = None
    execution_mode: str = "shadow"
    lane: str = "research"
    broker_order_authorized: bool = False
    risk_approval_allowed: bool = False
    execution_agent_allowed: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


def build_shadow_trade_plan(request: ShadowPlanRequest) -> ShadowTradePlan:
    candidate = _to_dict(request.candidate)
    symbol = _candidate_symbol(candidate)
    if not symbol:
        raise ValueError("shadow candidate requires symbol")

    profile = _profile(candidate)
    status = str(profile.get("status") or "").strip().lower()
    opportunity_score = _finite(profile.get("opportunity_score"))
    if opportunity_score is None:
        raise ValueError("shadow candidate requires opportunity_score")
    if profile.get("fail_closed") is True:
        raise ValueError("fail-closed opportunity evidence cannot enter shadow lane")
    if status not in {"qualified", "review"} or opportunity_score < RESEARCH_MIN_OPPORTUNITY_SCORE:
        raise ValueError("candidate is not eligible for research shadow lane")

    context = _to_dict(profile.get("execution_context"))
    quote_status = str(context.get("quote_status") or "unverified").strip().lower()
    market_session = str(context.get("market_session") or "unverified").strip().lower()
    if quote_status in {"market_closed", "stale_quote", "missing_quote_timestamp"}:
        raise ValueError(f"shadow_waits_for_fresh_quote:{quote_status}")
    if market_session not in {"regular", "unverified", "not_applicable", ""}:
        raise ValueError(f"shadow_waits_for_regular_session:{market_session}")

    decision_price = _finite(context.get("current_price"))
    if decision_price is None or decision_price <= 0:
        raise ValueError("shadow candidate requires positive current_price")

    spread_bps = _finite(context.get("spread_bps"))
    spread_bps_for_fill = max(0.0, spread_bps or 0.0)
    ask = _finite(context.get("ask"))
    bid = _finite(context.get("bid"))
    estimated_half_spread = decision_price * spread_bps_for_fill / 20_000.0
    simulated_fill = ask if ask and ask > 0 else decision_price + estimated_half_spread
    simulated_slippage_bps = ((simulated_fill - decision_price) / decision_price) * 10_000.0

    strategy_id = str(profile.get("preferred_strategy_hint") or "unassigned")
    signal_seed = (
        f"{request.correlation_id}|{symbol}|{strategy_id}|{opportunity_score:.8f}"
    )
    signal_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"shadow-signal:{signal_seed}"))
    trade_seed = f"{request.account_id}|{signal_id}|{strategy_id}"
    shadow_trade_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"shadow-trade:{trade_seed}"))

    metadata = _to_dict(candidate.get("metadata"))
    market_regime = metadata.get("market_regime")
    if isinstance(market_regime, dict):
        market_regime = market_regime.get("regime") or market_regime.get("label")

    return ShadowTradePlan(
        shadow_trade_id=shadow_trade_id,
        signal_id=signal_id,
        account_id=request.account_id,
        correlation_id=request.correlation_id,
        symbol=symbol,
        strategy_id=strategy_id,
        strategy_version=request.strategy_version,
        decision_price=decision_price,
        bid=bid,
        ask=ask,
        spread_bps=spread_bps,
        simulated_fill_price=round(simulated_fill, 8),
        simulated_slippage_bps=round(simulated_slippage_bps, 6),
        scanner_score=_score(candidate, "candidate_score", "confidence_score", "score"),
        opportunity_score=opportunity_score,
        market_regime=str(market_regime) if market_regime else None,
        source_commit_sha=request.source_commit_sha,
        metadata={
            "opportunity_profile_schema": profile.get("schema_version"),
            "opportunity_status": status,
            "workflow_status": profile.get("workflow_status"),
            "preferred_strategy_hint": profile.get("preferred_strategy_hint"),
            "strategy_affinity": profile.get("strategy_affinity") or {},
            "atr_pct": _finite(context.get("atr_pct")),
            "relative_volume": _finite(context.get("relative_volume")),
            "quote_status": quote_status,
            "market_session": market_session,
        },
    )


def build_shadow_plans(
    *,
    account_id: int | str,
    candidates: List[Dict[str, Any]],
    correlation_id: str,
) -> tuple[List[ShadowTradePlan], List[Dict[str, str]]]:
    plans: List[ShadowTradePlan] = []
    rejected: List[Dict[str, str]] = []
    for candidate in candidates:
        try:
            plans.append(
                build_shadow_trade_plan(
                    ShadowPlanRequest(
                        account_id=account_id,
                        candidate=candidate,
                        correlation_id=correlation_id,
                    )
                )
            )
        except (TypeError, ValueError) as exc:
            rejected.append(
                {
                    "symbol": _candidate_symbol(candidate) or "UNKNOWN",
                    "reason": str(exc),
                }
            )
    return plans, rejected


def shadow_position_key(symbol: str, strategy_id: str) -> str:
    return f"{symbol.strip().upper()}|{strategy_id.strip().lower()}"


def group_shadow_ledger(
    observations: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in observations:
        item = _to_dict(row)
        trade_id = str(item.get("shadow_trade_id") or "").strip()
        if not trade_id:
            continue
        grouped.setdefault(trade_id, []).append(item)
    for rows in grouped.values():
        rows.sort(key=lambda item: str(item.get("event_time") or ""))
    return grouped


def open_shadow_trades(
    observations: Iterable[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    open_by_key: Dict[str, List[Dict[str, Any]]] = {}
    for rows in group_shadow_ledger(observations).values():
        if not rows or any(row.get("event_type") == "exit_simulated" for row in rows):
            continue
        signal = next(
            (row for row in rows if row.get("event_type") == "signal_decision"),
            rows[0],
        )
        key = shadow_position_key(
            str(signal.get("symbol") or ""),
            str(signal.get("strategy_id") or "unassigned"),
        )
        current = open_by_key.get(key)
        if current is None or str(rows[-1].get("event_time") or "") > str(
            current[-1].get("event_time") or ""
        ):
            open_by_key[key] = rows
    return open_by_key


def _base_event(plan: ShadowTradePlan) -> Dict[str, Any]:
    return {
        "shadow_trade_id": plan.shadow_trade_id,
        "account_id": plan.account_id,
        "correlation_id": plan.correlation_id,
        "signal_id": plan.signal_id,
        "strategy_id": plan.strategy_id,
        "strategy_version": plan.strategy_version,
        "symbol": plan.symbol,
        "side": plan.side,
        "decision_price": plan.decision_price,
        "bid": plan.bid,
        "ask": plan.ask,
        "spread_bps": plan.spread_bps,
        "stop_loss": None,
        "take_profit": None,
        "market_regime": plan.market_regime,
        "scanner_score": plan.scanner_score,
        "opportunity_score": plan.opportunity_score,
        "source_commit_sha": plan.source_commit_sha,
        "execution_mode": "shadow",
        "broker_order_authorized": False,
    }


def build_signal_event(plan: ShadowTradePlan) -> Dict[str, Any]:
    return {
        **_base_event(plan),
        "event_key": "signal",
        "event_type": "signal_decision",
        "simulated_fill_price": None,
        "simulated_slippage_bps": None,
        "metadata": {**plan.metadata, "lane": "research"},
    }


def build_entry_event(plan: ShadowTradePlan) -> Dict[str, Any]:
    return {
        **_base_event(plan),
        "event_key": "entry",
        "event_type": "entry_simulated",
        "simulated_fill_price": plan.simulated_fill_price,
        "simulated_slippage_bps": plan.simulated_slippage_bps,
        "metadata": {**plan.metadata, "lane": "research"},
    }


def _entry_from_events(events: Iterable[Dict[str, Any]]) -> Dict[str, Any] | None:
    return next(
        (_to_dict(row) for row in events if row.get("event_type") == "entry_simulated"),
        None,
    )


def _signal_from_events(events: Iterable[Dict[str, Any]]) -> Dict[str, Any] | None:
    return next(
        (_to_dict(row) for row in events if row.get("event_type") == "signal_decision"),
        None,
    )


def _previous_extrema(events: Iterable[Dict[str, Any]]) -> tuple[float, float]:
    mfe = 0.0
    mae = 0.0
    for row in events:
        if row.get("event_type") != "mark":
            continue
        observed_mfe = _finite(row.get("mfe_pct"))
        observed_mae = _finite(row.get("mae_pct"))
        if observed_mfe is not None:
            mfe = max(mfe, observed_mfe)
        if observed_mae is not None:
            mae = min(mae, observed_mae)
    return mfe, mae


def build_mark_event(
    *,
    events: List[Dict[str, Any]],
    current_plan: ShadowTradePlan,
    cycle_id: str,
) -> Dict[str, Any]:
    signal = _signal_from_events(events)
    entry = _entry_from_events(events)
    if signal is None or entry is None:
        raise ValueError("open shadow trade is missing signal or entry evidence")
    entry_price = _finite(entry.get("simulated_fill_price"))
    if entry_price is None or entry_price <= 0:
        raise ValueError("open shadow trade has invalid simulated entry price")
    move = current_plan.decision_price / entry_price - 1.0
    previous_mfe, previous_mae = _previous_extrema(events)
    mfe = max(previous_mfe, move)
    mae = min(previous_mae, move)
    return {
        "shadow_trade_id": signal["shadow_trade_id"],
        "event_key": f"mark:{cycle_id}",
        "account_id": signal["account_id"],
        "correlation_id": current_plan.correlation_id,
        "signal_id": signal["signal_id"],
        "strategy_id": signal.get("strategy_id") or current_plan.strategy_id,
        "strategy_version": signal.get("strategy_version"),
        "symbol": signal["symbol"],
        "side": signal.get("side") or "buy",
        "event_type": "mark",
        "decision_price": signal.get("decision_price"),
        "bid": current_plan.bid,
        "ask": current_plan.ask,
        "spread_bps": current_plan.spread_bps,
        "simulated_fill_price": entry_price,
        "simulated_slippage_bps": entry.get("simulated_slippage_bps"),
        "market_regime": current_plan.market_regime or signal.get("market_regime"),
        "scanner_score": current_plan.scanner_score,
        "opportunity_score": current_plan.opportunity_score,
        "mfe_pct": round(mfe, 8),
        "mae_pct": round(mae, 8),
        "source_commit_sha": current_plan.source_commit_sha or signal.get("source_commit_sha"),
        "execution_mode": "shadow",
        "broker_order_authorized": False,
        "metadata": {
            "lane": "research",
            "cycle_id": cycle_id,
            "mark_price": current_plan.decision_price,
            "atr_pct": current_plan.metadata.get("atr_pct"),
            "relative_volume": current_plan.metadata.get("relative_volume"),
            "quote_status": current_plan.metadata.get("quote_status"),
        },
    }


def _mark_count(events: Iterable[Dict[str, Any]]) -> int:
    return len(
        {
            str(row.get("event_key") or row.get("event_id") or "")
            for row in events
            if row.get("event_type") == "mark"
        }
    )


def shadow_exit_reason(
    *,
    events: List[Dict[str, Any]],
    current_plan: ShadowTradePlan,
    max_marks: int = DEFAULT_SHADOW_MAX_MARKS,
) -> str | None:
    entry = _entry_from_events(events)
    if entry is None:
        return None
    entry_price = _finite(entry.get("simulated_fill_price"))
    if entry_price is None or entry_price <= 0:
        return None
    move = current_plan.decision_price / entry_price - 1.0
    signal = _signal_from_events(events) or {}
    signal_metadata = _to_dict(signal.get("metadata"))
    atr_pct = _finite(signal_metadata.get("atr_pct"))
    if atr_pct is None:
        atr_pct = _finite(current_plan.metadata.get("atr_pct"))
    if atr_pct is not None and atr_pct > 0:
        if move <= -atr_pct:
            return "shadow_stop_atr"
        if move >= 2.0 * atr_pct:
            return "shadow_take_profit_2atr"
    if _mark_count(events) >= max(1, int(max_marks)):
        return "shadow_time_horizon"
    return None


def build_exit_event(
    *,
    events: List[Dict[str, Any]],
    current_plan: ShadowTradePlan,
    cycle_id: str,
    exit_reason: str,
    cost_buffer_bps: float = DEFAULT_SHADOW_COST_BUFFER_BPS,
) -> Dict[str, Any]:
    signal = _signal_from_events(events)
    entry = _entry_from_events(events)
    if signal is None or entry is None:
        raise ValueError("shadow exit requires signal and entry evidence")
    entry_price = _finite(entry.get("simulated_fill_price"))
    decision_price = _finite(current_plan.decision_price)
    if entry_price is None or entry_price <= 0 or decision_price is None or decision_price <= 0:
        raise ValueError("shadow exit requires positive prices")

    half_spread = decision_price * max(current_plan.spread_bps or 0.0, 0.0) / 20_000.0
    exit_price = (
        current_plan.bid
        if current_plan.bid is not None and current_plan.bid > 0
        else decision_price - half_spread
    )
    exit_price = max(exit_price, 0.00000001)
    gross_return = exit_price / entry_price - 1.0
    entry_slippage_pct = abs(entry_price - _finite(signal.get("decision_price")) or 0.0) / max(
        _finite(signal.get("decision_price")) or entry_price,
        1e-12,
    )
    exit_slippage_pct = abs(decision_price - exit_price) / decision_price
    estimated_cost_pct = (
        entry_slippage_pct
        + exit_slippage_pct
        + max(0.0, float(cost_buffer_bps)) / 10_000.0
    )
    net_return = gross_return - estimated_cost_pct
    mfe, mae = _previous_extrema(events)
    entry_time = _parse_datetime(entry.get("event_time"))
    holding = None
    if entry_time is not None:
        holding = max(0.0, (datetime.now(timezone.utc) - entry_time).total_seconds())

    return {
        "shadow_trade_id": signal["shadow_trade_id"],
        "event_key": "exit",
        "account_id": signal["account_id"],
        "correlation_id": current_plan.correlation_id,
        "signal_id": signal["signal_id"],
        "strategy_id": signal.get("strategy_id") or current_plan.strategy_id,
        "strategy_version": signal.get("strategy_version"),
        "symbol": signal["symbol"],
        "side": signal.get("side") or "buy",
        "event_type": "exit_simulated",
        "decision_price": signal.get("decision_price"),
        "bid": current_plan.bid,
        "ask": current_plan.ask,
        "spread_bps": current_plan.spread_bps,
        "simulated_fill_price": entry_price,
        "simulated_slippage_bps": entry.get("simulated_slippage_bps"),
        "market_regime": current_plan.market_regime or signal.get("market_regime"),
        "scanner_score": current_plan.scanner_score,
        "opportunity_score": current_plan.opportunity_score,
        "mfe_pct": round(mfe, 8),
        "mae_pct": round(mae, 8),
        "exit_price": round(exit_price, 8),
        "exit_reason": exit_reason,
        "gross_return_pct": round(gross_return, 8),
        "estimated_cost_pct": round(estimated_cost_pct, 8),
        "net_return_pct": round(net_return, 8),
        "holding_period_seconds": round(holding, 3) if holding is not None else None,
        "source_commit_sha": current_plan.source_commit_sha or signal.get("source_commit_sha"),
        "execution_mode": "shadow",
        "broker_order_authorized": False,
        "metadata": {
            "lane": "research",
            "cycle_id": cycle_id,
            "mark_count": _mark_count(events),
            "quote_status": current_plan.metadata.get("quote_status"),
        },
    }

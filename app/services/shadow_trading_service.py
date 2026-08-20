from __future__ import annotations

import uuid
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field


SHADOW_TRADE_SCHEMA_VERSION = "manager-shadow-trade.v1"
RESEARCH_MIN_OPPORTUNITY_SCORE = 0.50


def _to_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return {}


def _profile(candidate: Dict[str, Any]) -> Dict[str, Any]:
    metadata = _to_dict(candidate.get("metadata"))
    details = _to_dict(metadata.get("details"))
    bundle = _to_dict(details.get("data_bundle")) or _to_dict(metadata.get("data_bundle"))
    return _to_dict(bundle.get("opportunity_profile"))


def _score(candidate: Dict[str, Any], *keys: str) -> float | None:
    for key in keys:
        value = candidate.get(key)
        if value is None:
            continue
        try:
            number = float(value)
            return number / 100.0 if number > 1.0 else number
        except (TypeError, ValueError):
            continue
    return None


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
    symbol = str(candidate.get("symbol") or candidate.get("ticker") or "").strip().upper()
    if not symbol:
        raise ValueError("shadow candidate requires symbol")

    profile = _profile(candidate)
    status = str(profile.get("status") or "").strip().lower()
    try:
        opportunity_score = float(profile.get("opportunity_score"))
    except (TypeError, ValueError) as exc:
        raise ValueError("shadow candidate requires opportunity_score") from exc
    if status not in {"qualified", "review"} or opportunity_score < RESEARCH_MIN_OPPORTUNITY_SCORE:
        raise ValueError("candidate is not eligible for research shadow lane")

    context = _to_dict(profile.get("execution_context"))
    try:
        decision_price = float(context.get("current_price"))
    except (TypeError, ValueError) as exc:
        raise ValueError("shadow candidate requires current_price") from exc
    if decision_price <= 0:
        raise ValueError("shadow decision_price must be positive")

    spread_bps = context.get("spread_bps")
    try:
        spread_bps = float(spread_bps) if spread_bps is not None else None
    except (TypeError, ValueError):
        spread_bps = None
    spread_bps_for_fill = max(0.0, spread_bps or 0.0)
    ask = context.get("ask")
    bid = context.get("bid")
    try:
        ask = float(ask) if ask is not None else None
        bid = float(bid) if bid is not None else None
    except (TypeError, ValueError):
        ask, bid = None, None

    estimated_half_spread = decision_price * spread_bps_for_fill / 20_000.0
    simulated_fill = ask if ask and ask > 0 else decision_price + estimated_half_spread
    simulated_slippage_bps = ((simulated_fill - decision_price) / decision_price) * 10_000.0

    strategy_id = str(profile.get("preferred_strategy_hint") or "unassigned")
    signal_seed = f"{request.correlation_id}|{symbol}|{strategy_id}|{opportunity_score:.8f}"
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
            "preferred_strategy_hint": profile.get("preferred_strategy_hint"),
            "strategy_affinity": profile.get("strategy_affinity") or {},
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
                    "symbol": str(candidate.get("symbol") or "unknown").upper(),
                    "reason": str(exc),
                }
            )
    return plans, rejected

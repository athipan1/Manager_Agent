from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..shadow_database_client import ShadowDatabaseAgentClient
from ..services.shadow_observation_mapper import shadow_plan_to_observation
from ..services.shadow_trading_service import (
    DEFAULT_SHADOW_COST_BUFFER_BPS,
    DEFAULT_SHADOW_MAX_MARKS,
    ShadowPlanRequest,
    ShadowTradePlan,
    build_entry_event,
    build_exit_event,
    build_mark_event,
    build_shadow_plans,
    build_shadow_trade_plan,
    build_signal_event,
    open_shadow_trades,
    shadow_exit_reason,
    shadow_position_key,
)


router = APIRouter(prefix="/shadow-trading", tags=["shadow-trading"])


class ShadowBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: int | str
    correlation_id: str = Field(min_length=1, max_length=200)
    candidates: list[dict]


class ShadowHourlyRequest(ShadowBatchRequest):
    cycle_id: str = Field(min_length=1, max_length=200)
    max_marks: int = Field(default=DEFAULT_SHADOW_MAX_MARKS, ge=1, le=240)
    cost_buffer_bps: float = Field(
        default=DEFAULT_SHADOW_COST_BUFFER_BPS,
        ge=0,
        le=100,
    )


async def _persist_shadow_plan(plan: ShadowTradePlan) -> dict:
    observation = shadow_plan_to_observation(plan)
    async with ShadowDatabaseAgentClient() as database_client:
        return await database_client.create_shadow_observation(
            observation,
            plan.correlation_id,
        )


async def _persist_observation(
    database_client: ShadowDatabaseAgentClient,
    observation: dict,
    correlation_id: str,
) -> dict:
    return await database_client.create_shadow_observation(
        observation,
        correlation_id,
    )


def _merge_event(events: list[dict], event: dict) -> list[dict]:
    identity = str(event.get("event_id") or "")
    event_key = str(event.get("event_key") or "")
    event_type = str(event.get("event_type") or "")
    merged = list(events)
    for existing in merged:
        if identity and str(existing.get("event_id") or "") == identity:
            return merged
        if (
            event_key
            and str(existing.get("event_key") or "") == event_key
            and str(existing.get("event_type") or "") == event_type
        ):
            return merged
    merged.append(event)
    return merged


@router.post("/plan", response_model=ShadowTradePlan)
def plan_shadow_trade(payload: ShadowPlanRequest) -> ShadowTradePlan:
    """Build one hypothetical trade plan without Risk or Execution authority."""

    try:
        return build_shadow_trade_plan(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/plan/batch")
def plan_shadow_trades(payload: ShadowBatchRequest):
    """Build research-lane plans. This endpoint never calls a broker-facing agent."""

    plans, rejected = build_shadow_plans(
        account_id=payload.account_id,
        candidates=payload.candidates,
        correlation_id=payload.correlation_id,
    )
    return {
        "schema_version": "manager-shadow-trade-batch.v2",
        "execution_mode": "shadow",
        "broker_order_authorized": False,
        "risk_approval_allowed": False,
        "execution_agent_allowed": False,
        "risk_call_count": 0,
        "execution_call_count": 0,
        "broker_order_count": 0,
        "planned_count": len(plans),
        "rejected_count": len(rejected),
        "plans": [plan.model_dump(mode="json") for plan in plans],
        "rejected": rejected,
    }


@router.post("/record")
async def record_shadow_trade(payload: ShadowPlanRequest):
    """Build and append a Shadow signal event to Database_Agent only."""

    try:
        plan = build_shadow_trade_plan(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        persisted = await _persist_shadow_plan(plan)
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="shadow_observation_persistence_failed",
        ) from exc
    return {
        "schema_version": "manager-shadow-record.v2",
        "execution_mode": "shadow",
        "broker_order_authorized": False,
        "risk_approval_allowed": False,
        "execution_agent_allowed": False,
        "risk_call_count": 0,
        "execution_call_count": 0,
        "broker_order_count": 0,
        "plan": plan.model_dump(mode="json"),
        "observation": persisted,
    }


@router.post("/record/batch")
async def record_shadow_trades(payload: ShadowBatchRequest):
    """Append eligible research candidates to Database without Risk/Execution calls."""

    plans, rejected = build_shadow_plans(
        account_id=payload.account_id,
        candidates=payload.candidates,
        correlation_id=payload.correlation_id,
    )
    persisted: list[dict] = []
    persistence_errors: list[dict[str, str]] = []
    for plan in plans:
        try:
            persisted.append(await _persist_shadow_plan(plan))
        except Exception:
            persistence_errors.append(
                {"symbol": plan.symbol, "reason": "shadow_observation_persistence_failed"}
            )
    return {
        "schema_version": "manager-shadow-record-batch.v2",
        "execution_mode": "shadow",
        "broker_order_authorized": False,
        "risk_approval_allowed": False,
        "execution_agent_allowed": False,
        "risk_call_count": 0,
        "execution_call_count": 0,
        "broker_order_count": 0,
        "planned_count": len(plans),
        "recorded_count": len(persisted),
        "rejected_count": len(rejected),
        "persistence_error_count": len(persistence_errors),
        "observations": persisted,
        "rejected": rejected,
        "persistence_errors": persistence_errors,
    }


@router.post("/hourly")
async def run_hourly_shadow_lane(payload: ShadowHourlyRequest):
    """Advance research candidates through an idempotent broker-isolated lifecycle.

    This route imports no Risk/Execution client and has no broker credential path. It
    only reads/writes Database_Agent's Shadow ledger. Replaying the same cycle_id
    returns the same signal/entry/mark/exit events because Database event keys are
    deterministic and unique per shadow trade.
    """

    plans, rejected = build_shadow_plans(
        account_id=payload.account_id,
        candidates=payload.candidates,
        correlation_id=payload.correlation_id,
    )
    actions: list[dict] = []
    persistence_errors: list[dict[str, str]] = []

    try:
        async with ShadowDatabaseAgentClient() as database_client:
            ledger = await database_client.list_shadow_observations(
                account_id=payload.account_id,
                correlation_id=payload.correlation_id,
                limit=1000,
            )
            open_by_key = open_shadow_trades(ledger)

            for plan in plans:
                key = shadow_position_key(plan.symbol, plan.strategy_id)
                events = list(open_by_key.get(key) or [])
                try:
                    if not events:
                        signal = await _persist_observation(
                            database_client,
                            build_signal_event(plan),
                            payload.correlation_id,
                        )
                        events = _merge_event(events, signal)
                        entry = await _persist_observation(
                            database_client,
                            build_entry_event(plan),
                            payload.correlation_id,
                        )
                        events = _merge_event(events, entry)
                        actions.extend(
                            [
                                {
                                    "symbol": plan.symbol,
                                    "shadow_trade_id": plan.shadow_trade_id,
                                    "event_type": "signal_decision",
                                    "event_id": signal.get("event_id"),
                                },
                                {
                                    "symbol": plan.symbol,
                                    "shadow_trade_id": plan.shadow_trade_id,
                                    "event_type": "entry_simulated",
                                    "event_id": entry.get("event_id"),
                                },
                            ]
                        )

                    mark = await _persist_observation(
                        database_client,
                        build_mark_event(
                            events=events,
                            current_plan=plan,
                            cycle_id=payload.cycle_id,
                        ),
                        payload.correlation_id,
                    )
                    events = _merge_event(events, mark)
                    actions.append(
                        {
                            "symbol": plan.symbol,
                            "shadow_trade_id": mark.get("shadow_trade_id"),
                            "event_type": "mark",
                            "event_id": mark.get("event_id"),
                            "event_key": mark.get("event_key"),
                        }
                    )

                    reason = shadow_exit_reason(
                        events=events,
                        current_plan=plan,
                        max_marks=payload.max_marks,
                    )
                    if reason:
                        exit_event = await _persist_observation(
                            database_client,
                            build_exit_event(
                                events=events,
                                current_plan=plan,
                                cycle_id=payload.cycle_id,
                                exit_reason=reason,
                                cost_buffer_bps=payload.cost_buffer_bps,
                            ),
                            payload.correlation_id,
                        )
                        events = _merge_event(events, exit_event)
                        actions.append(
                            {
                                "symbol": plan.symbol,
                                "shadow_trade_id": exit_event.get("shadow_trade_id"),
                                "event_type": "exit_simulated",
                                "event_id": exit_event.get("event_id"),
                                "net_return_pct": exit_event.get("net_return_pct"),
                                "exit_reason": exit_event.get("exit_reason"),
                            }
                        )
                except Exception as exc:
                    persistence_errors.append(
                        {
                            "symbol": plan.symbol,
                            "reason": str(exc)[:240]
                            or "shadow_lifecycle_persistence_failed",
                        }
                    )

            closed = await database_client.list_closed_shadow_outcomes(
                account_id=payload.account_id,
                correlation_id=payload.correlation_id,
                limit=1000,
            )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail="shadow_ledger_unavailable",
        ) from exc

    return {
        "schema_version": "manager-shadow-hourly.v1",
        "execution_mode": "shadow",
        "broker_order_authorized": False,
        "risk_approval_allowed": False,
        "execution_agent_allowed": False,
        "risk_call_count": 0,
        "execution_call_count": 0,
        "broker_order_count": 0,
        "cycle_id": payload.cycle_id,
        "planned_count": len(plans),
        "rejected_count": len(rejected),
        "action_count": len(actions),
        "persistence_error_count": len(persistence_errors),
        "closed_observation_count": int(closed.get("closed_observation_count") or 0),
        "closed_outcomes": closed.get("outcomes") or [],
        "actions": actions,
        "rejected": rejected,
        "persistence_errors": persistence_errors,
    }

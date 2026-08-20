from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..shadow_database_client import ShadowDatabaseAgentClient
from ..services.shadow_observation_mapper import shadow_plan_to_observation
from ..services.shadow_trading_service import (
    ShadowPlanRequest,
    ShadowTradePlan,
    build_shadow_plans,
    build_shadow_trade_plan,
)


router = APIRouter(prefix="/shadow-trading", tags=["shadow-trading"])


class ShadowBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: int | str
    correlation_id: str = Field(min_length=1, max_length=200)
    candidates: list[dict]


async def _persist_shadow_plan(plan: ShadowTradePlan) -> dict:
    observation = shadow_plan_to_observation(plan)
    async with ShadowDatabaseAgentClient() as database_client:
        return await database_client.create_shadow_observation(
            observation,
            plan.correlation_id,
        )


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
        "schema_version": "manager-shadow-trade-batch.v1",
        "execution_mode": "shadow",
        "broker_order_authorized": False,
        "risk_approval_allowed": False,
        "execution_agent_allowed": False,
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
        "schema_version": "manager-shadow-record.v1",
        "execution_mode": "shadow",
        "broker_order_authorized": False,
        "risk_approval_allowed": False,
        "execution_agent_allowed": False,
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
        "schema_version": "manager-shadow-record-batch.v1",
        "execution_mode": "shadow",
        "broker_order_authorized": False,
        "risk_approval_allowed": False,
        "execution_agent_allowed": False,
        "planned_count": len(plans),
        "recorded_count": len(persisted),
        "rejected_count": len(rejected),
        "persistence_error_count": len(persistence_errors),
        "observations": persisted,
        "rejected": rejected,
        "persistence_errors": persistence_errors,
    }

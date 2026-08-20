from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

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

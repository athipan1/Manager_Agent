from __future__ import annotations

from fastapi import APIRouter

from ..strategy_promotion_policy import (
    STRATEGY_PROMOTION_SCHEMA_VERSION,
    StrategyPromotionDecision,
    StrategyPromotionRequest,
    evaluate_strategy_promotion,
)


router = APIRouter(prefix="/strategy-promotion", tags=["strategy-promotion"])


@router.post("/evaluate", response_model=StrategyPromotionDecision)
def evaluate_strategy_promotion_route(
    payload: StrategyPromotionRequest,
) -> StrategyPromotionDecision:
    """Evaluate one evidence-gated stage transition without persisting or trading."""

    decision = evaluate_strategy_promotion(payload)
    decision.schema_version = STRATEGY_PROMOTION_SCHEMA_VERSION
    return decision

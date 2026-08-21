from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


STRATEGY_PROMOTION_SCHEMA_VERSION = "manager-strategy-promotion.v1"
MINIMUM_SHADOW_OBSERVATIONS_FOR_PAPER = 100


class StrategyPromotionStage(str, Enum):
    RESEARCH = "research"
    PRE_HOLDOUT_PASS = "pre_holdout_pass"
    FINAL_HOLDOUT_PASS = "final_holdout_pass"
    SHADOW = "shadow"
    PAPER = "paper"
    PAPER_PROVEN = "paper_proven"
    CANARY = "canary"
    SCALE = "scale"
    DEGRADED = "degraded"
    QUARANTINED = "quarantined"
    RETIRED = "retired"


class StrategyPromotionEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pre_holdout_passed: bool = False
    final_holdout_passed: bool = False
    final_holdout_rejected: bool = False
    shadow_observations: int = Field(default=0, ge=0)
    paper_observations: int = Field(default=0, ge=0)
    net_expectancy_r: Optional[float] = None
    profit_factor: Optional[float] = Field(default=None, ge=0)
    max_drawdown_pct: Optional[float] = Field(default=None, ge=0, le=1)
    execution_cost_calibrated: bool = False
    broker_reconciliation_mismatches: int = Field(default=0, ge=0)
    duplicate_order_count: int = Field(default=0, ge=0)
    rejected_order_count: int = Field(default=0, ge=0)
    protection_coverage_pct: float = Field(default=0.0, ge=0, le=1)
    emergency_halt_verified: bool = False
    operator_live_approval: bool = False


class StrategyPromotionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_shadow_observations: int = Field(
        default=MINIMUM_SHADOW_OBSERVATIONS_FOR_PAPER,
        ge=MINIMUM_SHADOW_OBSERVATIONS_FOR_PAPER,
    )
    min_paper_observations: int = Field(default=100, ge=1)
    min_net_expectancy_r: float = 0.0
    min_profit_factor: float = Field(default=1.10, ge=0)
    max_drawdown_pct: float = Field(default=0.10, gt=0, le=1)
    min_protection_coverage_pct: float = Field(default=1.0, ge=0, le=1)
    allow_live_progression: bool = False


class StrategyPromotionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy_id: str = Field(min_length=1, max_length=128)
    current_stage: StrategyPromotionStage
    requested_stage: StrategyPromotionStage
    evidence: StrategyPromotionEvidence = Field(
        default_factory=StrategyPromotionEvidence
    )
    policy: StrategyPromotionPolicy = Field(
        default_factory=StrategyPromotionPolicy
    )


class StrategyPromotionDecision(BaseModel):
    schema_version: str = STRATEGY_PROMOTION_SCHEMA_VERSION
    strategy_id: str
    current_stage: StrategyPromotionStage
    requested_stage: StrategyPromotionStage
    allowed: bool
    decision: str
    requires_human_review: bool = True
    auto_execute: bool = False
    broker_order_authorized: bool = False
    reasons: list[str] = Field(default_factory=list)
    failed_gates: list[str] = Field(default_factory=list)


_FORWARD_TRANSITIONS = {
    StrategyPromotionStage.RESEARCH: StrategyPromotionStage.PRE_HOLDOUT_PASS,
    StrategyPromotionStage.PRE_HOLDOUT_PASS: StrategyPromotionStage.FINAL_HOLDOUT_PASS,
    StrategyPromotionStage.FINAL_HOLDOUT_PASS: StrategyPromotionStage.SHADOW,
    StrategyPromotionStage.SHADOW: StrategyPromotionStage.PAPER,
    StrategyPromotionStage.PAPER: StrategyPromotionStage.PAPER_PROVEN,
    StrategyPromotionStage.PAPER_PROVEN: StrategyPromotionStage.CANARY,
    StrategyPromotionStage.CANARY: StrategyPromotionStage.SCALE,
}

_DEGRADABLE_STAGES = {
    StrategyPromotionStage.SHADOW,
    StrategyPromotionStage.PAPER,
    StrategyPromotionStage.PAPER_PROVEN,
    StrategyPromotionStage.CANARY,
    StrategyPromotionStage.SCALE,
}


def _paper_quality_gates(
    evidence: StrategyPromotionEvidence,
    policy: StrategyPromotionPolicy,
) -> dict[str, bool]:
    return {
        "paper_observation_count": (
            evidence.paper_observations >= policy.min_paper_observations
        ),
        "positive_net_expectancy": (
            evidence.net_expectancy_r is not None
            and evidence.net_expectancy_r > policy.min_net_expectancy_r
        ),
        "profit_factor": (
            evidence.profit_factor is not None
            and evidence.profit_factor >= policy.min_profit_factor
        ),
        "max_drawdown": (
            evidence.max_drawdown_pct is not None
            and evidence.max_drawdown_pct <= policy.max_drawdown_pct
        ),
        "execution_cost_calibrated": evidence.execution_cost_calibrated,
        "broker_reconciliation_clean": (
            evidence.broker_reconciliation_mismatches == 0
        ),
        "duplicate_orders_zero": evidence.duplicate_order_count == 0,
        "protection_coverage": (
            evidence.protection_coverage_pct
            >= policy.min_protection_coverage_pct
        ),
        "emergency_halt_verified": evidence.emergency_halt_verified,
    }


def evaluate_strategy_promotion(
    request: StrategyPromotionRequest,
) -> StrategyPromotionDecision:
    current = request.current_stage
    target = request.requested_stage
    evidence = request.evidence
    policy = request.policy

    if target == StrategyPromotionStage.DEGRADED:
        if current not in _DEGRADABLE_STAGES:
            return StrategyPromotionDecision(
                strategy_id=request.strategy_id,
                current_stage=current,
                requested_stage=target,
                allowed=False,
                decision="invalid_transition",
                reasons=["Only active validation/trading stages can be degraded."],
            )
        degradation_signals = {
            "non_positive_expectancy": (
                evidence.net_expectancy_r is not None
                and evidence.net_expectancy_r <= 0
            ),
            "broker_reconciliation_mismatch": (
                evidence.broker_reconciliation_mismatches > 0
            ),
            "duplicate_order_detected": evidence.duplicate_order_count > 0,
            "protection_coverage_incomplete": (
                evidence.protection_coverage_pct
                < policy.min_protection_coverage_pct
            ),
        }
        triggered = [name for name, value in degradation_signals.items() if value]
        return StrategyPromotionDecision(
            strategy_id=request.strategy_id,
            current_stage=current,
            requested_stage=target,
            allowed=bool(triggered),
            decision="degrade" if triggered else "keep_current_stage",
            reasons=(
                ["Safety/performance degradation evidence requires rollback."]
                if triggered
                else ["No degradation signal is present."]
            ),
            failed_gates=triggered,
        )

    if current == StrategyPromotionStage.DEGRADED and target == StrategyPromotionStage.QUARANTINED:
        return StrategyPromotionDecision(
            strategy_id=request.strategy_id,
            current_stage=current,
            requested_stage=target,
            allowed=True,
            decision="quarantine",
            reasons=["Degraded strategy may be quarantined for investigation."],
        )

    if current == StrategyPromotionStage.QUARANTINED and target == StrategyPromotionStage.RETIRED:
        return StrategyPromotionDecision(
            strategy_id=request.strategy_id,
            current_stage=current,
            requested_stage=target,
            allowed=True,
            decision="retire",
            reasons=["Quarantined strategy may be retired."],
        )

    expected_target = _FORWARD_TRANSITIONS.get(current)
    if expected_target != target:
        return StrategyPromotionDecision(
            strategy_id=request.strategy_id,
            current_stage=current,
            requested_stage=target,
            allowed=False,
            decision="invalid_transition",
            reasons=[
                "Strategy stages cannot be skipped or promoted out of order."
            ],
        )

    gates: dict[str, bool]
    if target == StrategyPromotionStage.PRE_HOLDOUT_PASS:
        gates = {"pre_holdout_passed": evidence.pre_holdout_passed}
    elif target == StrategyPromotionStage.FINAL_HOLDOUT_PASS:
        gates = {
            "pre_holdout_passed": evidence.pre_holdout_passed,
            "final_holdout_passed": (
                evidence.final_holdout_passed
                and not evidence.final_holdout_rejected
            ),
        }
    elif target == StrategyPromotionStage.SHADOW:
        gates = {
            "final_holdout_passed": (
                evidence.final_holdout_passed
                and not evidence.final_holdout_rejected
            )
        }
    elif target == StrategyPromotionStage.PAPER:
        gates = {
            "shadow_observation_count": (
                evidence.shadow_observations >= policy.min_shadow_observations
            ),
            "positive_shadow_expectancy": (
                evidence.net_expectancy_r is not None
                and evidence.net_expectancy_r > policy.min_net_expectancy_r
            ),
        }
    elif target == StrategyPromotionStage.PAPER_PROVEN:
        gates = _paper_quality_gates(evidence, policy)
    elif target in {StrategyPromotionStage.CANARY, StrategyPromotionStage.SCALE}:
        gates = {
            **_paper_quality_gates(evidence, policy),
            "live_progression_enabled": policy.allow_live_progression,
            "operator_live_approval": evidence.operator_live_approval,
        }
    else:
        gates = {}

    failed = [name for name, passed in gates.items() if not passed]
    allowed = not failed
    return StrategyPromotionDecision(
        strategy_id=request.strategy_id,
        current_stage=current,
        requested_stage=target,
        allowed=allowed,
        decision="promotion_review_passed" if allowed else "promotion_blocked",
        reasons=(
            [
                "All evidence gates for this transition passed. State persistence "
                "and any execution action remain separate responsibilities."
            ]
            if allowed
            else ["One or more required evidence gates did not pass."]
        ),
        failed_gates=failed,
    )

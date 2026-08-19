from fastapi.testclient import TestClient

from app.main_modular import app
from app.strategy_promotion_policy import (
    StrategyPromotionRequest,
    evaluate_strategy_promotion,
)


def _request(current, target, **evidence_overrides):
    evidence = {
        "pre_holdout_passed": True,
        "final_holdout_passed": True,
        "final_holdout_rejected": False,
        "shadow_observations": 50,
        "paper_observations": 120,
        "net_expectancy_r": 0.20,
        "profit_factor": 1.40,
        "max_drawdown_pct": 0.05,
        "execution_cost_calibrated": True,
        "broker_reconciliation_mismatches": 0,
        "duplicate_order_count": 0,
        "rejected_order_count": 0,
        "protection_coverage_pct": 1.0,
        "emergency_halt_verified": True,
        "operator_live_approval": False,
    }
    evidence.update(evidence_overrides)
    return StrategyPromotionRequest.model_validate(
        {
            "strategy_id": "trend-v6",
            "current_stage": current,
            "requested_stage": target,
            "evidence": evidence,
        }
    )


def test_research_cannot_skip_pre_holdout_stage():
    decision = evaluate_strategy_promotion(
        _request("research", "final_holdout_pass")
    )
    assert decision.allowed is False
    assert decision.decision == "invalid_transition"


def test_pre_holdout_transition_requires_pre_holdout_evidence():
    blocked = evaluate_strategy_promotion(
        _request("research", "pre_holdout_pass", pre_holdout_passed=False)
    )
    passed = evaluate_strategy_promotion(
        _request("research", "pre_holdout_pass")
    )
    assert blocked.allowed is False
    assert blocked.failed_gates == ["pre_holdout_passed"]
    assert passed.allowed is True
    assert passed.auto_execute is False
    assert passed.broker_order_authorized is False


def test_final_holdout_rejection_blocks_transition():
    decision = evaluate_strategy_promotion(
        _request(
            "pre_holdout_pass",
            "final_holdout_pass",
            final_holdout_passed=True,
            final_holdout_rejected=True,
        )
    )
    assert decision.allowed is False
    assert "final_holdout_passed" in decision.failed_gates


def test_shadow_to_paper_requires_shadow_sample_and_positive_expectancy():
    sample_blocked = evaluate_strategy_promotion(
        _request("shadow", "paper", shadow_observations=10)
    )
    expectancy_blocked = evaluate_strategy_promotion(
        _request("shadow", "paper", net_expectancy_r=0.0)
    )
    passed = evaluate_strategy_promotion(_request("shadow", "paper"))

    assert sample_blocked.allowed is False
    assert "shadow_observation_count" in sample_blocked.failed_gates
    assert expectancy_blocked.allowed is False
    assert "positive_shadow_expectancy" in expectancy_blocked.failed_gates
    assert passed.allowed is True


def test_paper_proven_requires_profit_execution_and_safety_evidence():
    decision = evaluate_strategy_promotion(
        _request(
            "paper",
            "paper_proven",
            paper_observations=20,
            net_expectancy_r=-0.01,
            profit_factor=0.9,
            max_drawdown_pct=0.20,
            execution_cost_calibrated=False,
            broker_reconciliation_mismatches=1,
            duplicate_order_count=1,
            protection_coverage_pct=0.8,
            emergency_halt_verified=False,
        )
    )

    assert decision.allowed is False
    assert set(decision.failed_gates) == {
        "paper_observation_count",
        "positive_net_expectancy",
        "profit_factor",
        "max_drawdown",
        "execution_cost_calibrated",
        "broker_reconciliation_clean",
        "duplicate_orders_zero",
        "protection_coverage",
        "emergency_halt_verified",
    }


def test_paper_proven_can_pass_without_authorizing_any_order():
    decision = evaluate_strategy_promotion(
        _request("paper", "paper_proven")
    )
    assert decision.allowed is True
    assert decision.decision == "promotion_review_passed"
    assert decision.requires_human_review is True
    assert decision.auto_execute is False
    assert decision.broker_order_authorized is False


def test_live_canary_is_blocked_by_default_even_with_good_paper_evidence():
    decision = evaluate_strategy_promotion(
        _request(
            "paper_proven",
            "canary",
            operator_live_approval=True,
        )
    )
    assert decision.allowed is False
    assert "live_progression_enabled" in decision.failed_gates


def test_live_canary_needs_both_policy_enable_and_operator_approval():
    request = _request("paper_proven", "canary")
    request.policy.allow_live_progression = True
    blocked = evaluate_strategy_promotion(request)
    assert blocked.allowed is False
    assert blocked.failed_gates == ["operator_live_approval"]

    request.evidence.operator_live_approval = True
    passed = evaluate_strategy_promotion(request)
    assert passed.allowed is True
    assert passed.broker_order_authorized is False


def test_active_strategy_can_degrade_on_reconciliation_fault():
    decision = evaluate_strategy_promotion(
        _request(
            "paper",
            "degraded",
            broker_reconciliation_mismatches=1,
        )
    )
    assert decision.allowed is True
    assert decision.decision == "degrade"
    assert "broker_reconciliation_mismatch" in decision.failed_gates


def test_degraded_can_quarantine_then_retire_only_in_order():
    quarantine = evaluate_strategy_promotion(
        _request("degraded", "quarantined")
    )
    retire = evaluate_strategy_promotion(
        _request("quarantined", "retired")
    )
    direct_retire = evaluate_strategy_promotion(
        _request("degraded", "retired")
    )
    assert quarantine.allowed is True
    assert retire.allowed is True
    assert direct_retire.allowed is False


def test_http_endpoint_is_evaluation_only():
    client = TestClient(app)
    response = client.post(
        "/strategy-promotion/evaluate",
        json=_request("paper", "paper_proven").model_dump(mode="json"),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "manager-strategy-promotion.v1"
    assert body["allowed"] is True
    assert body["auto_execute"] is False
    assert body["broker_order_authorized"] is False

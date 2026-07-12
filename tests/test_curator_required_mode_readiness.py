from app.contracts import StandardAgentResponse
from app.services.curator_required_mode_readiness import (
    evaluate_curator_required_mode_readiness,
)
from app.workflows.gated_guarded_discovery_workflow import _attach_curator_observability


def _summary(**overrides):
    value = {
        "readiness_source": "database_cumulative",
        "ensemble_observations": 50,
        "availability_rate": 0.99,
        "contract_valid_rate": 1.0,
        "unsafe_contract_count": 0,
        "would_pass_required_gate": 10,
    }
    value.update(overrides)
    return value


def _signal():
    return {
        "symbol": "ACGL",
        "status": "success",
        "mode": "shadow_ensemble",
        "ensemble": {
            "selected_skill_count": 3,
            "consensus": {"signal": "buy", "agreement": 0.8},
            "executions": [{"skill_id": "a"}],
        },
        "gate": {
            "allowed": True,
            "contract_valid": True,
            "trusted_signal": "buy",
            "agreement": 0.8,
            "minimum_agreement": 0.6,
            "rejection_codes": [],
        },
    }


def test_evaluator_marks_eligible_but_requires_operator_approval(monkeypatch):
    monkeypatch.delenv("CURATOR_REQUIRED_MODE_MIN_OBSERVATIONS", raising=False)
    result = evaluate_curator_required_mode_readiness(_summary())

    assert result["status"] == "eligible_for_operator_approval"
    assert result["eligible"] is True
    assert result["operator_approval_required"] is True
    assert result["automatic_activation_allowed"] is False
    assert result["blockers"] == []
    assert result["alert"]["severity"] == "action_required"


def test_evaluator_reports_all_safety_and_coverage_blockers():
    result = evaluate_curator_required_mode_readiness(
        _summary(
            readiness_source="current_run",
            ensemble_observations=20,
            availability_rate=0.95,
            contract_valid_rate=0.98,
            unsafe_contract_count=1,
            would_pass_required_gate=0,
        )
    )

    assert result["eligible"] is False
    assert result["status"] == "not_ready"
    assert result["blockers"] == [
        "cumulative_readiness_unavailable",
        "observations_below_target",
        "availability_below_threshold",
        "contract_valid_rate_below_threshold",
        "unsafe_contracts_detected",
        "no_candidates_would_pass_required_gate",
    ]


def test_thresholds_are_configurable_but_cannot_auto_activate(monkeypatch):
    monkeypatch.setenv("CURATOR_REQUIRED_MODE_MIN_OBSERVATIONS", "100")
    monkeypatch.setenv("CURATOR_REQUIRED_MODE_MIN_AVAILABILITY", "0.995")
    result = evaluate_curator_required_mode_readiness(_summary())

    assert result["eligible"] is False
    assert "observations_below_target" in result["blockers"]
    assert "availability_below_threshold" in result["blockers"]
    assert result["automatic_activation_allowed"] is False


def test_guarded_response_adds_operator_alert_only_when_eligible():
    readiness = {
        "observations": 50,
        "observation_target": 50,
        "available": 50,
        "unavailable": 0,
        "availability_rate": 1.0,
        "contract_valid": 50,
        "contract_invalid": 0,
        "contract_valid_rate": 1.0,
        "unsafe_contract_count": 0,
        "buy_count": 10,
        "hold_count": 40,
        "sell_count": 0,
        "unknown_count": 0,
        "would_pass_required_gate": 10,
        "would_be_blocked": 40,
        "required_mode_eligible": True,
        "blockers": [],
    }
    response = StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp="2026-07-12T00:00:00Z",
        data={
            "curator_signals": [_signal()],
            "curator_observation_readiness": readiness,
            "portfolio_summary": {},
        },
        metadata={},
    )

    result = _attach_curator_observability(response)

    evaluation = result.data["curator_required_mode_readiness"]
    assert evaluation["eligible"] is True
    assert evaluation["automatic_activation_allowed"] is False
    assert result.data["operator_alerts"][0]["code"] == (
        "curator_required_mode_operator_approval_ready"
    )
    assert result.data["portfolio_summary"]["curator_required_mode_status"] == (
        "eligible_for_operator_approval"
    )

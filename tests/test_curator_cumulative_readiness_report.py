from app.contracts import StandardAgentResponse
from app.services.curator_observability import summarize_curator_signals
from app.workflows.gated_guarded_discovery_workflow import _attach_curator_observability


def _signal(symbol="ACGL", signal="buy", agreement=0.8, allowed=True):
    return {
        "symbol": symbol,
        "status": "success",
        "mode": "shadow_ensemble",
        "ensemble": {
            "selected_skill_count": 3,
            "consensus": {
                "signal": signal,
                "agreement": agreement,
                "state": "consensus",
            },
            "executions": [{"skill_id": "a"}, {"skill_id": "b"}],
        },
        "gate": {
            "allowed": allowed,
            "contract_valid": True,
            "trusted_signal": signal,
            "agreement": agreement,
            "minimum_agreement": 0.6,
            "rejection_codes": [],
        },
    }


def _readiness():
    return {
        "observations": 42,
        "observation_target": 50,
        "available": 41,
        "unavailable": 1,
        "availability_rate": 41 / 42,
        "contract_valid": 42,
        "contract_invalid": 0,
        "contract_valid_rate": 1.0,
        "unsafe_contract_count": 0,
        "buy_count": 15,
        "hold_count": 25,
        "sell_count": 2,
        "unknown_count": 0,
        "average_agreement": 0.71,
        "would_pass_required_gate": 15,
        "would_be_blocked": 27,
        "required_mode_eligible": False,
        "blockers": ["observations_below_target", "availability_below_99_percent"],
    }


def test_summary_prefers_database_cumulative_readiness():
    summary = summarize_curator_signals(
        [_signal()],
        cumulative_readiness=_readiness(),
    )

    assert summary["readiness_source"] == "database_cumulative"
    assert summary["observations"] == 42
    assert summary["ensemble_observations"] == 42
    assert summary["signal_counts"] == {
        "buy": 15,
        "hold": 25,
        "sell": 2,
        "unknown": 0,
    }
    assert summary["would_pass_required_gate"] == 15
    assert summary["would_be_blocked"] == 27
    assert summary["readiness_blockers"] == [
        "observations_below_target",
        "availability_below_99_percent",
    ]
    assert summary["current_run"]["observations"] == 1
    assert summary["rows"][0]["symbol"] == "ACGL"


def test_summary_falls_back_to_current_run_without_database_readiness():
    summary = summarize_curator_signals([_signal()])

    assert summary["readiness_source"] == "current_run"
    assert summary["observations"] == 1
    assert summary["signal_counts"]["buy"] == 1
    assert summary["readiness_blockers"] == []


def test_guarded_response_attaches_cumulative_summary_without_persistence_logic():
    response = StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp="2026-07-12T00:00:00Z",
        data={
            "curator_signals": [_signal()],
            "curator_observation_readiness": _readiness(),
            "portfolio_summary": {},
        },
        metadata={},
    )

    result = _attach_curator_observability(response)
    summary = result.data["curator_ensemble_summary"]

    assert summary["readiness_source"] == "database_cumulative"
    assert summary["observations"] == 42
    assert result.data["portfolio_summary"]["curator_readiness_source"] == (
        "database_cumulative"
    )
    assert result.data["portfolio_summary"][
        "curator_ensemble_would_be_blocked"
    ] == 27

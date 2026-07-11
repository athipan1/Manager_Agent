from app.services.curator_observability import summarize_curator_signals
from scripts.render_hourly_portfolio_report import render_curator_signals


def _ensemble_signal(
    symbol: str,
    *,
    signal: str,
    agreement: float | None,
    allowed: bool,
    contract_valid: bool = True,
    status: str = "success",
    rejection_codes=None,
    selected_skill_count: int = 3,
):
    return {
        "symbol": symbol,
        "status": status,
        "mode": "shadow_ensemble",
        "ensemble": {
            "selected_skill_count": selected_skill_count,
            "consensus": {
                "signal": signal,
                "agreement": agreement,
                "state": "consensus" if signal != "hold" else "insufficient_agreement",
            },
            "manager_contract": {
                "trusted_signal": signal,
                "requires_risk_gate": True,
                "direct_execution_allowed": False,
            },
            "executions": [{"skill_id": f"skill-{index}"} for index in range(selected_skill_count)],
        },
        "gate": {
            "allowed": allowed,
            "contract_valid": contract_valid,
            "trusted_signal": signal,
            "consensus_signal": signal,
            "consensus_state": "consensus" if allowed else "insufficient_agreement",
            "agreement": agreement,
            "minimum_agreement": 0.60,
            "rejection_codes": rejection_codes or [],
            "requires_risk_gate": True,
            "direct_execution_allowed": False,
        },
    }


def test_summarize_curator_shadow_ensemble_observations():
    summary = summarize_curator_signals(
        [
            _ensemble_signal("ACGL", signal="buy", agreement=0.80, allowed=True),
            _ensemble_signal(
                "ADBE",
                signal="hold",
                agreement=0.55,
                allowed=False,
                rejection_codes=["agreement_below_threshold"],
            ),
            _ensemble_signal(
                "CINF",
                signal="hold",
                agreement=None,
                allowed=False,
                contract_valid=False,
                status="invalid_contract",
                rejection_codes=["broker_access_must_be_false"],
            ),
            {
                "symbol": "BKNG",
                "status": "unavailable",
                "mode": "shadow_ensemble",
                "gate": {
                    "allowed": False,
                    "contract_valid": False,
                    "trusted_signal": "hold",
                    "agreement": None,
                    "rejection_codes": ["curator_shadow_ensemble_unavailable"],
                },
            },
        ]
    )

    assert summary["mode"] == "shadow_ensemble"
    assert summary["ensemble_observations"] == 4
    assert summary["available"] == 3
    assert summary["unavailable"] == 1
    assert summary["availability_rate"] == 0.75
    assert summary["contract_valid"] == 2
    assert summary["contract_invalid"] == 2
    assert summary["unsafe_contract_count"] == 1
    assert summary["signal_counts"]["buy"] == 1
    assert summary["signal_counts"]["hold"] == 3
    assert summary["average_agreement"] == 0.675
    assert summary["would_pass_required_gate"] == 1
    assert summary["would_be_blocked"] == 3
    assert summary["required_mode_eligible"] is False
    assert summary["rows"][0]["selected_skill_count"] == 3


def test_render_curator_shadow_ensemble_summary_and_symbol_table():
    signals = [
        _ensemble_signal("ACGL", signal="buy", agreement=0.80, allowed=True),
        _ensemble_signal(
            "ADBE",
            signal="hold",
            agreement=0.55,
            allowed=False,
            rejection_codes=["agreement_below_threshold"],
        ),
    ]
    data = {
        "curator_signals": signals,
        "curator_ensemble_summary": summarize_curator_signals(signals),
    }
    lines = []

    render_curator_signals(lines, data)
    output = "\n".join(lines)

    assert "## Curator Shadow Ensemble" in output
    assert "Deployment Mode: `advisory`" in output
    assert "Availability Rate: `100.0%`" in output
    assert "BUY / HOLD / SELL: `1` / `1` / `0`" in output
    assert "Average Agreement: `67.5%`" in output
    assert "Would Pass Required Gate: `1`" in output
    assert "Would Be Blocked: `1`" in output
    assert "Required Mode Readiness: `not_ready`" in output
    assert "ACGL" in output
    assert "80.0%" in output
    assert "ADBE" in output
    assert "agreement_below_threshold" in output


def test_single_skill_observability_remains_backward_compatible():
    summary = summarize_curator_signals(
        [
            {
                "symbol": "ACGL",
                "status": "success",
                "skill_id": "skill-1",
                "execution": {
                    "execution_status": "success",
                    "output": {"signal": "hold", "confidence": 0.55},
                },
            }
        ]
    )

    assert summary["mode"] == "single_skill"
    assert summary["observations"] == 1
    assert summary["signal_counts"]["hold"] == 1
    assert summary["ensemble_observations"] == 0

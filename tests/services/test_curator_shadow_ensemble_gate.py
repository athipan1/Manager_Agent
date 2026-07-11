import pytest

from app.curator_ensemble_client import validate_shadow_ensemble_contract
from app.services import curator_signal_service


def _valid_ensemble(*, signal="buy", agreement=0.75, state="consensus"):
    return {
        "advisory_only": True,
        "broker_access": False,
        "order_placement": False,
        "consensus": {
            "signal": signal,
            "state": state,
            "agreement": agreement,
        },
        "manager_contract": {
            "trusted_signal": signal,
            "requires_risk_gate": True,
            "direct_execution_allowed": False,
        },
    }


def test_valid_buy_consensus_passes_contract():
    result = validate_shadow_ensemble_contract(
        _valid_ensemble(),
        minimum_agreement=0.60,
    )

    assert result["contract_valid"] is True
    assert result["allowed"] is True
    assert result["trusted_signal"] == "buy"
    assert result["rejection_codes"] == []


def test_hold_consensus_is_valid_but_not_allowed():
    result = validate_shadow_ensemble_contract(
        _valid_ensemble(signal="hold", agreement=0.90),
        minimum_agreement=0.60,
    )

    assert result["contract_valid"] is True
    assert result["allowed"] is False
    assert "trusted_signal_not_buy" in result["rejection_codes"]


def test_low_agreement_fails_closed():
    result = validate_shadow_ensemble_contract(
        _valid_ensemble(agreement=0.40),
        minimum_agreement=0.60,
    )

    assert result["contract_valid"] is True
    assert result["allowed"] is False
    assert "agreement_below_threshold" in result["rejection_codes"]


@pytest.mark.parametrize(
    "field,value,code",
    [
        ("advisory_only", False, "advisory_only_must_be_true"),
        ("broker_access", True, "broker_access_must_be_false"),
        ("order_placement", True, "order_placement_must_be_false"),
    ],
)
def test_unsafe_top_level_contract_is_rejected(field, value, code):
    payload = _valid_ensemble()
    payload[field] = value

    result = validate_shadow_ensemble_contract(payload, minimum_agreement=0.60)

    assert result["contract_valid"] is False
    assert result["allowed"] is False
    assert code in result["rejection_codes"]


def test_direct_execution_permission_is_rejected():
    payload = _valid_ensemble()
    payload["manager_contract"]["direct_execution_allowed"] = True

    result = validate_shadow_ensemble_contract(payload, minimum_agreement=0.60)

    assert result["contract_valid"] is False
    assert result["allowed"] is False
    assert "direct_execution_allowed_must_be_false" in result["rejection_codes"]


def test_signal_mismatch_is_rejected():
    payload = _valid_ensemble()
    payload["manager_contract"]["trusted_signal"] = "sell"

    result = validate_shadow_ensemble_contract(payload, minimum_agreement=0.60)

    assert result["contract_valid"] is False
    assert result["allowed"] is False
    assert "trusted_signal_consensus_mismatch" in result["rejection_codes"]


@pytest.mark.asyncio
async def test_required_gate_keeps_only_valid_buy_payload(monkeypatch):
    monkeypatch.setattr(curator_signal_service, "CURATOR_SHADOW_ENSEMBLE_ENABLED", True)
    monkeypatch.setattr(curator_signal_service, "CURATOR_SHADOW_ENSEMBLE_REQUIRED", True)

    async def fake_signal(*, symbol, analysis, correlation_id, account_id):
        allowed = symbol == "ACGL"
        return {
            "status": "success",
            "mode": "shadow_ensemble",
            "ensemble": _valid_ensemble(
                signal="buy" if allowed else "hold",
                agreement=0.80,
            ),
            "gate": {
                "allowed": allowed,
                "contract_valid": True,
                "trusted_signal": "buy" if allowed else "hold",
                "consensus_signal": "buy" if allowed else "hold",
                "consensus_state": "consensus",
                "agreement": 0.80,
                "minimum_agreement": 0.60,
                "rejection_codes": [] if allowed else ["trusted_signal_not_buy"],
                "requires_risk_gate": True,
                "direct_execution_allowed": False,
            },
        }

    monkeypatch.setattr(curator_signal_service, "_shadow_ensemble_signal", fake_signal)

    enriched, signals = await curator_signal_service.enrich_payloads_with_curator_signals(
        payloads=[{"ticker": "ACGL"}, {"ticker": "ADBE"}],
        correlation_id="cid-1",
        account_id="paper-1",
    )

    assert [item["ticker"] for item in enriched] == ["ACGL"]
    assert len(signals) == 2
    assert signals[0]["gate"]["allowed"] is True
    assert signals[1]["gate"]["allowed"] is False
    assert enriched[0]["metadata"]["curator_shadow_ensemble_required"] is True


@pytest.mark.asyncio
async def test_advisory_mode_keeps_rejected_payload(monkeypatch):
    monkeypatch.setattr(curator_signal_service, "CURATOR_SHADOW_ENSEMBLE_ENABLED", True)
    monkeypatch.setattr(curator_signal_service, "CURATOR_SHADOW_ENSEMBLE_REQUIRED", False)

    async def fake_signal(*, symbol, analysis, correlation_id, account_id):
        return {
            "status": "success",
            "mode": "shadow_ensemble",
            "gate": {
                "allowed": False,
                "contract_valid": True,
                "trusted_signal": "hold",
                "consensus_signal": "hold",
                "consensus_state": "consensus",
                "agreement": 0.90,
                "minimum_agreement": 0.60,
                "rejection_codes": ["trusted_signal_not_buy"],
                "requires_risk_gate": True,
                "direct_execution_allowed": False,
            },
        }

    monkeypatch.setattr(curator_signal_service, "_shadow_ensemble_signal", fake_signal)

    enriched, signals = await curator_signal_service.enrich_payloads_with_curator_signals(
        payloads=[{"ticker": "CINF"}],
        correlation_id="cid-1",
    )

    assert [item["ticker"] for item in enriched] == ["CINF"]
    assert signals[0]["gate"]["allowed"] is False


@pytest.mark.asyncio
async def test_required_gate_fails_closed_when_curator_unavailable(monkeypatch):
    monkeypatch.setattr(curator_signal_service, "CURATOR_SHADOW_ENSEMBLE_ENABLED", True)
    monkeypatch.setattr(curator_signal_service, "CURATOR_SHADOW_ENSEMBLE_REQUIRED", True)

    async def unavailable(*, symbol, analysis, correlation_id, account_id):
        return {
            "status": "unavailable",
            "mode": "shadow_ensemble",
            "gate": {
                "allowed": False,
                "contract_valid": False,
                "trusted_signal": "hold",
                "consensus_signal": "hold",
                "consensus_state": "unavailable",
                "agreement": None,
                "minimum_agreement": 0.60,
                "rejection_codes": ["curator_shadow_ensemble_unavailable"],
                "requires_risk_gate": True,
                "direct_execution_allowed": False,
            },
        }

    monkeypatch.setattr(curator_signal_service, "_shadow_ensemble_signal", unavailable)

    enriched, signals = await curator_signal_service.enrich_payloads_with_curator_signals(
        payloads=[{"ticker": "CINF"}],
        correlation_id="cid-1",
    )

    assert enriched == []
    assert signals[0]["status"] == "unavailable"
    assert signals[0]["gate"]["allowed"] is False

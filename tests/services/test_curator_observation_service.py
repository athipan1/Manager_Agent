import pytest

from app.services.curator_observation_service import (
    build_curator_observations,
    persist_curator_observations_best_effort,
)
from app.services import curator_signal_service


def _shadow_signal(symbol="ACGL", account_id="paper-1", allowed=True):
    return {
        "symbol": symbol,
        "account_id": account_id,
        "status": "success",
        "mode": "shadow_ensemble",
        "ensemble": {
            "consensus": {
                "signal": "buy" if allowed else "hold",
                "state": "consensus",
                "agreement": 0.8,
            },
            "selected_skills": [{"skill_id": "champion"}, {"skill_id": "shadow"}],
            "executions": [{"skill_id": "champion"}, {"skill_id": "shadow"}],
        },
        "gate": {
            "allowed": allowed,
            "contract_valid": True,
            "trusted_signal": "buy" if allowed else "hold",
            "consensus_signal": "buy" if allowed else "hold",
            "consensus_state": "consensus",
            "agreement": 0.8,
            "minimum_agreement": 0.6,
            "rejection_codes": [] if allowed else ["trusted_signal_not_buy"],
            "requires_risk_gate": True,
            "direct_execution_allowed": False,
        },
    }


def test_build_curator_observation_normalizes_ensemble_signal():
    observations = build_curator_observations(
        [_shadow_signal()],
        correlation_id="corr-1",
    )

    assert observations == [
        {
            "account_id": "paper-1",
            "correlation_id": "corr-1",
            "symbol": "ACGL",
            "mode": "shadow_ensemble",
            "status": "success",
            "available": True,
            "signal": "buy",
            "agreement": 0.8,
            "contract_valid": True,
            "would_pass_required_gate": True,
            "selected_skill_count": 2,
            "execution_count": 2,
            "minimum_agreement": 0.6,
            "rejection_codes": [],
            "metadata": {
                "source": "manager-agent",
                "consensus_state": "consensus",
                "requires_risk_gate": True,
                "direct_execution_allowed": False,
                "reason": None,
            },
        }
    ]


def test_build_curator_observation_records_unavailable_as_hold():
    observations = build_curator_observations(
        [
            {
                "symbol": "CINF",
                "account_id": 1,
                "status": "unavailable",
                "mode": "shadow_ensemble",
                "reason": "timeout",
                "gate": {
                    "allowed": False,
                    "contract_valid": False,
                    "trusted_signal": "hold",
                    "agreement": None,
                    "minimum_agreement": 0.6,
                    "rejection_codes": ["curator_shadow_ensemble_unavailable"],
                    "requires_risk_gate": True,
                    "direct_execution_allowed": False,
                },
            }
        ],
        correlation_id="corr-2",
    )

    assert observations[0]["available"] is False
    assert observations[0]["signal"] == "hold"
    assert observations[0]["would_pass_required_gate"] is False
    assert observations[0]["metadata"]["reason"] == "timeout"


@pytest.mark.asyncio
async def test_persist_curator_observations_posts_one_batch(monkeypatch):
    captured = {}

    class FakeResponse:
        data = {"created_count": 1}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def _post(self, endpoint, correlation_id, json_data):
            captured.update(
                endpoint=endpoint,
                correlation_id=correlation_id,
                json_data=json_data,
            )
            return {"status": "success", "data": {"created_count": 1}}

        def validate_standard_response(self, response):
            return FakeResponse()

    monkeypatch.setattr(
        "app.services.curator_observation_service.DatabaseAgentClient",
        FakeClient,
    )

    result = await persist_curator_observations_best_effort(
        [_shadow_signal()],
        correlation_id="corr-batch",
    )

    assert result == {"status": "success", "created_count": 1}
    assert captured["endpoint"] == "/curator/observations/batch"
    assert captured["correlation_id"] == "corr-batch"
    assert len(captured["json_data"]["observations"]) == 1


@pytest.mark.asyncio
async def test_persistence_failure_is_best_effort(monkeypatch):
    class FailingClient:
        async def __aenter__(self):
            raise RuntimeError("database unavailable")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "app.services.curator_observation_service.DatabaseAgentClient",
        FailingClient,
    )

    result = await persist_curator_observations_best_effort(
        [_shadow_signal()],
        correlation_id="corr-fail",
    )

    assert result["status"] == "unavailable"
    assert result["created_count"] == 0
    assert "database unavailable" in result["reason"]


@pytest.mark.asyncio
async def test_enrichment_persists_all_signals_once(monkeypatch):
    monkeypatch.setattr(curator_signal_service, "CURATOR_SHADOW_ENSEMBLE_ENABLED", True)
    monkeypatch.setattr(curator_signal_service, "CURATOR_SHADOW_ENSEMBLE_REQUIRED", False)

    async def fake_shadow(*, symbol, analysis, correlation_id, account_id):
        return {key: value for key, value in _shadow_signal(symbol, account_id).items() if key not in {"symbol", "account_id"}}

    captured = {}

    async def fake_persist(signals, *, correlation_id):
        captured["signals"] = list(signals)
        captured["correlation_id"] = correlation_id
        return {"status": "success", "created_count": len(captured["signals"])}

    monkeypatch.setattr(curator_signal_service, "_shadow_ensemble_signal", fake_shadow)
    monkeypatch.setattr(
        curator_signal_service,
        "persist_curator_observations_best_effort",
        fake_persist,
    )

    enriched, signals = await curator_signal_service.enrich_payloads_with_curator_signals(
        payloads=[{"ticker": "ACGL"}, {"ticker": "ADBE"}],
        correlation_id="corr-flow",
        account_id="paper-1",
    )

    assert len(enriched) == 2
    assert len(signals) == 2
    assert captured["correlation_id"] == "corr-flow"
    assert [row["symbol"] for row in captured["signals"]] == ["ACGL", "ADBE"]

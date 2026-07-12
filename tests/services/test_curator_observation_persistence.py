from types import SimpleNamespace

import pytest

from app.contracts import DatabaseEndpoints
from app.services.curator_observation_persistence import (
    build_curator_observation_payloads,
    persist_curator_observations,
)


def _ensemble_signal(
    symbol: str,
    *,
    signal: str = "buy",
    agreement: float | None = 0.8,
    allowed: bool = True,
    contract_valid: bool = True,
    status: str = "success",
    rejection_codes=None,
):
    return {
        "symbol": symbol,
        "status": status,
        "mode": "shadow_ensemble",
        "ensemble": {
            "selected_skill_count": 3,
            "consensus": {
                "signal": signal,
                "agreement": agreement,
                "state": "consensus" if allowed else "insufficient_agreement",
            },
            "manager_contract": {
                "trusted_signal": signal,
                "requires_risk_gate": True,
                "direct_execution_allowed": False,
            },
            "executions": [
                {"skill_id": "champion"},
                {"skill_id": "challenger"},
                {"skill_id": "shadow"},
            ],
        },
        "gate": {
            "allowed": allowed,
            "contract_valid": contract_valid,
            "trusted_signal": signal,
            "agreement": agreement,
            "minimum_agreement": 0.6,
            "rejection_codes": rejection_codes or [],
        },
    }


class FakeDatabaseClient:
    def __init__(self, *, fail_post: bool = False, fail_readiness: bool = False):
        self.fail_post = fail_post
        self.fail_readiness = fail_readiness
        self.post_calls = []
        self.get_calls = []

    async def _post(self, path, correlation_id, json_data=None):
        self.post_calls.append((path, correlation_id, json_data))
        if self.fail_post:
            raise RuntimeError("database unavailable")
        observations = (json_data or {}).get("observations") or []
        return {
            "status": "success",
            "agent_type": "database",
            "version": "1.1.0",
            "timestamp": "2026-07-11T20:00:00Z",
            "data": {
                "created_count": len(observations),
                "observations": observations,
            },
            "metadata": {},
            "error": None,
        }

    async def _get(self, path, correlation_id, params=None):
        self.get_calls.append((path, correlation_id, params))
        if self.fail_readiness:
            raise RuntimeError("readiness unavailable")
        return {
            "status": "success",
            "agent_type": "database",
            "version": "1.1.0",
            "timestamp": "2026-07-11T20:00:00Z",
            "data": {
                "observations": 12,
                "observation_target": 50,
                "required_mode_eligible": False,
                "blockers": ["observations_below_target"],
            },
            "metadata": {},
            "error": None,
        }

    def validate_standard_response(self, response):
        return SimpleNamespace(data=response.get("data"))


def test_build_curator_observation_payloads_matches_database_contract():
    rows = build_curator_observation_payloads(
        account_id="paper-1",
        correlation_id="run-123",
        curator_signals=[
            _ensemble_signal("acgl"),
            _ensemble_signal(
                "adbe",
                signal="hold",
                agreement=0.5,
                allowed=False,
                rejection_codes=["agreement_below_threshold"],
            ),
        ],
    )

    assert len(rows) == 2
    assert rows[0]["account_id"] == "paper-1"
    assert rows[0]["correlation_id"] == "run-123"
    assert rows[0]["symbol"] == "ACGL"
    assert rows[0]["mode"] == "shadow_ensemble"
    assert rows[0]["signal"] == "buy"
    assert rows[0]["agreement"] == 0.8
    assert rows[0]["contract_valid"] is True
    assert rows[0]["would_pass_required_gate"] is True
    assert rows[0]["selected_skill_count"] == 3
    assert rows[0]["execution_count"] == 3
    assert rows[0]["metadata"]["schema"] == "curator_observation.v1"
    assert rows[1]["rejection_codes"] == ["agreement_below_threshold"]


@pytest.mark.asyncio
async def test_persist_curator_observations_posts_batch_and_loads_readiness():
    db_client = FakeDatabaseClient()

    result = await persist_curator_observations(
        db_client=db_client,
        account_id="paper-1",
        correlation_id="run-123",
        curator_signals=[_ensemble_signal("ACGL")],
    )

    assert result["status"] == "persisted"
    assert result["attempted_count"] == 1
    assert result["persisted_count"] == 1
    assert result["readiness"]["observations"] == 12
    assert db_client.post_calls[0][0] == DatabaseEndpoints.CURATOR_OBSERVATIONS_BATCH
    assert db_client.get_calls[0][0] == DatabaseEndpoints.CURATOR_OBSERVATION_READINESS
    assert db_client.get_calls[0][2] == {
        "account_id": "paper-1",
        "mode": "shadow_ensemble",
        "observation_target": 50,
    }


@pytest.mark.asyncio
async def test_persistence_failure_is_fail_soft_for_trading_flow():
    db_client = FakeDatabaseClient(fail_post=True)

    result = await persist_curator_observations(
        db_client=db_client,
        account_id="paper-1",
        correlation_id="run-123",
        curator_signals=[_ensemble_signal("ACGL")],
    )

    assert result["status"] == "failed"
    assert result["reason"] == "database_persistence_failed"
    assert result["attempted_count"] == 1
    assert result["persisted_count"] == 0
    assert result["readiness"] is None


@pytest.mark.asyncio
async def test_readiness_failure_does_not_erase_successful_persistence():
    db_client = FakeDatabaseClient(fail_readiness=True)

    result = await persist_curator_observations(
        db_client=db_client,
        account_id="paper-1",
        correlation_id="run-123",
        curator_signals=[_ensemble_signal("ACGL")],
    )

    assert result["status"] == "persisted"
    assert result["persisted_count"] == 1
    assert result["readiness"] is None
    assert "readiness unavailable" in result["readiness_error"]


@pytest.mark.asyncio
async def test_empty_curator_signal_list_skips_database_calls():
    db_client = FakeDatabaseClient()

    result = await persist_curator_observations(
        db_client=db_client,
        account_id="paper-1",
        correlation_id="run-123",
        curator_signals=[],
    )

    assert result == {
        "status": "skipped",
        "reason": "no_curator_observations",
        "attempted_count": 0,
        "persisted_count": 0,
        "readiness": None,
    }
    assert db_client.post_calls == []
    assert db_client.get_calls == []

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.services.backtest_execution_gate import (
    filter_candidates_with_backtest_gate,
)
from app.services.promotion_database_adapter import (
    PromotionAuthorityError,
    PromotionDatabaseAdapter,
)


NOW = datetime(2026, 8, 3, 5, 0, tzinfo=timezone.utc)


def promotion(**updates):
    value = {
        "promotion_id": "promotion-1",
        "account_id": "1",
        "run_id": "backtest-run-1",
        "skill_id": "hourly-sma-crossover",
        "strategy_id": "trend-following-balanced-v1",
        "symbol": "AAPL",
        "timeframe": "1d",
        "dataset_fingerprint": "a" * 64,
        "engine_version": "backtest-agent-0.7.0",
        "validation_profile": "nested_walk_forward_v2",
        "state": "APPROVED_FOR_PAPER",
        "version": 5,
        "evidence_version": 1,
        "created_at": (NOW - timedelta(hours=2)).isoformat(),
        "updated_at": (NOW - timedelta(minutes=5)).isoformat(),
        "expires_at": (NOW + timedelta(days=1)).isoformat(),
    }
    value.update(updates)
    return value


class FakeDatabaseClient:
    def __init__(self, records, *, transition_error=False):
        self.records = [deepcopy(item) for item in records]
        self.transition_error = transition_error
        self.get_calls = []
        self.post_calls = []

    async def _get(self, path, correlation_id, **kwargs):
        self.get_calls.append(
            {
                "path": path,
                "correlation_id": correlation_id,
                "params": kwargs.get("params"),
            }
        )
        if not self.records:
            return {"status": "success", "data": None}
        return {"status": "success", "data": deepcopy(self.records.pop(0))}

    async def _post(
        self,
        path,
        correlation_id,
        json_data,
        extra_headers=None,
        **kwargs,
    ):
        self.post_calls.append(
            {
                "path": path,
                "correlation_id": correlation_id,
                "json": deepcopy(json_data),
                "extra_headers": deepcopy(extra_headers),
            }
        )
        if self.transition_error:
            raise RuntimeError("stale promotion version")
        approved = promotion(
            promotion_id=json_data.get("promotion_id", "promotion-1"),
            state="APPROVED_FOR_PAPER",
            version=json_data["expected_version"] + 1,
        )
        return {"status": "success", "data": approved}

    def validate_standard_response(self, response_data):
        if response_data.get("status") != "success":
            raise RuntimeError("upstream error")
        return SimpleNamespace(data=response_data.get("data"))


def positions():
    return [{"symbol": "AAPL", "quantity": 10}]


def payloads():
    return [{"symbol": "AAPL", "analysis": {"score": 0.9}}]


async def run_gate(client, **updates):
    arguments = {
        "db_client": client,
        "selected_positions": positions(),
        "position_analysis_payloads": payloads(),
        "correlation_id": "corr-1",
        "required": True,
        "skill_id": "hourly-sma-crossover",
        "strategy_id": "trend-following-balanced-v1",
        "strategy_ids": ["trend-following-balanced-v1"],
        "timeframe": "1d",
        "max_age_hours": 26,
        "now": NOW,
        "promotion_authority_required": True,
        "account_id": "1",
        "auto_approve": False,
    }
    arguments.update(updates)
    return await filter_candidates_with_backtest_gate(**arguments)


@pytest.mark.asyncio
async def test_exact_approved_promotion_is_execution_authority():
    client = FakeDatabaseClient([promotion()])
    result = await run_gate(client)

    assert result["summary"] == {
        "candidate_count": 1,
        "allowed_count": 1,
        "rejected_count": 0,
    }
    decision = result["decisions"][0]
    assert decision["allowed"] is True
    assert decision["promotion_state"] == "APPROVED_FOR_PAPER"
    assert decision["authority"] == "database-agent-backtest-promotion"
    assert decision["requires_risk_approval"] is True
    assert decision["broker_boundary"] == "execution-agent-only"
    assert client.post_calls == []
    assert client.get_calls[0]["path"] == "/backtests/promotions/latest/exact"
    assert client.get_calls[0]["params"]["account_id"] == "1"


@pytest.mark.asyncio
async def test_robustness_passed_requires_explicit_manager_approval_policy():
    client = FakeDatabaseClient([promotion(state="ROBUSTNESS_PASSED", version=4)])
    result = await run_gate(client, auto_approve=False)

    decision = result["decisions"][0]
    assert decision["allowed"] is False
    assert decision["rejection_codes"] == [
        "backtest_promotion_approval_required"
    ]
    assert client.post_calls == []


@pytest.mark.asyncio
async def test_manager_approval_uses_privileged_header_only_on_transition(monkeypatch):
    monkeypatch.setenv("BACKTEST_PROMOTION_APPROVAL_TOKEN", "approval-secret")
    client = FakeDatabaseClient([promotion(state="ROBUSTNESS_PASSED", version=4)])

    result = await run_gate(client, auto_approve=True)

    assert result["summary"]["allowed_count"] == 1
    assert len(client.post_calls) == 1
    call = client.post_calls[0]
    assert call["path"] == "/backtests/promotions/promotion-1/transition"
    assert call["extra_headers"] == {
        "X-PROMOTION-APPROVAL-KEY": "approval-secret"
    }
    assert "X-PROMOTION-APPROVAL-KEY" not in client.get_calls[0]
    assert call["json"]["expected_state"] == "ROBUSTNESS_PASSED"
    assert call["json"]["next_state"] == "APPROVED_FOR_PAPER"
    assert call["json"]["evidence_run_id"] == "backtest-run-1"
    assert call["json"]["metadata"]["requires_risk_approval"] is True
    assert call["json"]["metadata"][
        "execution_agent_only_broker_boundary"
    ] is True


@pytest.mark.asyncio
async def test_concurrent_approval_race_rereads_authority(monkeypatch):
    monkeypatch.setenv("BACKTEST_PROMOTION_APPROVAL_TOKEN", "approval-secret")
    client = FakeDatabaseClient(
        [
            promotion(state="ROBUSTNESS_PASSED", version=4),
            promotion(state="APPROVED_FOR_PAPER", version=5),
        ],
        transition_error=True,
    )

    result = await run_gate(client, auto_approve=True)

    assert result["summary"]["allowed_count"] == 1
    assert len(client.get_calls) == 2
    assert len(client.post_calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("state", "code"),
    [
        ("GENERATED", "backtest_promotion_not_robustness_passed"),
        ("VALIDATED", "backtest_promotion_not_robustness_passed"),
        ("OOS_PASSED", "backtest_promotion_not_robustness_passed"),
        ("FAILED", "backtest_promotion_terminal_failed"),
        ("REVOKED", "backtest_promotion_terminal_revoked"),
        ("EXPIRED", "backtest_promotion_terminal_expired"),
    ],
)
async def test_non_authoritative_states_fail_closed(state, code):
    client = FakeDatabaseClient([promotion(state=state)])
    result = await run_gate(client)

    assert result["summary"]["allowed_count"] == 0
    assert code in result["decisions"][0]["rejection_codes"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("updates", "code"),
    [
        ({"account_id": "2"}, "backtest_promotion_account_id_mismatch"),
        ({"strategy_id": "other"}, "backtest_promotion_strategy_id_mismatch"),
        ({"symbol": "MSFT"}, "backtest_promotion_symbol_mismatch"),
        ({"timeframe": "1h"}, "backtest_promotion_timeframe_mismatch"),
        ({"validation_profile": "legacy"}, "backtest_promotion_validation_profile_mismatch"),
        ({"expires_at": (NOW - timedelta(seconds=1)).isoformat()}, "backtest_promotion_expired"),
        ({"updated_at": (NOW - timedelta(days=2)).isoformat()}, "backtest_promotion_stale"),
    ],
)
async def test_identity_expiry_and_freshness_fail_closed(updates, code):
    client = FakeDatabaseClient([promotion(**updates)])
    result = await run_gate(client)

    assert result["summary"]["allowed_count"] == 0
    assert code in result["decisions"][0]["rejection_codes"]


@pytest.mark.asyncio
async def test_paper_observing_is_read_only_authority():
    client = FakeDatabaseClient([promotion(state="PAPER_OBSERVING", version=6)])
    result = await run_gate(client, auto_approve=True)

    assert result["summary"]["allowed_count"] == 1
    assert result["decisions"][0]["promotion_state"] == "PAPER_OBSERVING"
    assert client.post_calls == []


@pytest.mark.asyncio
async def test_disabled_gate_does_not_query_or_approve():
    client = FakeDatabaseClient([])
    result = await run_gate(client, required=False, auto_approve=True)

    assert result["status"] == "disabled"
    assert result["selected_positions"] == positions()
    assert client.get_calls == []
    assert client.post_calls == []


@pytest.mark.asyncio
async def test_approval_adapter_fails_closed_without_token(monkeypatch):
    monkeypatch.delenv("BACKTEST_PROMOTION_APPROVAL_TOKEN", raising=False)
    adapter = PromotionDatabaseAdapter(FakeDatabaseClient([]))
    with pytest.raises(PromotionAuthorityError, match="APPROVAL_TOKEN"):
        await adapter.approve_for_paper(
            promotion(state="ROBUSTNESS_PASSED", version=4),
            correlation_id="corr-1",
        )

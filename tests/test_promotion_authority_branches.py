from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app import config
from app.services import promotion_database_adapter as adapter_module
from app.services import promotion_execution_gate as gate
from app.services.promotion_database_adapter import (
    PromotionAuthorityError,
    PromotionDatabaseAdapter,
)


NOW = datetime(2026, 8, 3, 5, 0, tzinfo=timezone.utc)


class SampleModel(BaseModel):
    value: int


class DuckModel:
    def model_dump(self, mode="json"):
        return {"value": 3}


class AdapterClient:
    def __init__(self, data=None, approved=None):
        self.data = data
        self.approved = approved
        self.get_calls = []
        self.post_calls = []

    async def _get(self, path, correlation_id, **kwargs):
        self.get_calls.append((path, correlation_id, kwargs))
        return {"status": "success", "data": self.data}

    async def _post(
        self,
        path,
        correlation_id,
        json_data,
        extra_headers=None,
        **kwargs,
    ):
        self.post_calls.append(
            (path, correlation_id, json_data, extra_headers, kwargs)
        )
        return {"status": "success", "data": self.approved}

    def validate_standard_response(self, response):
        return SimpleNamespace(data=response.get("data"))


def exact_promotion(**updates):
    value = {
        "promotion_id": "promotion-1",
        "account_id": "1",
        "run_id": "run-1",
        "skill_id": "skill-1",
        "strategy_id": "strategy-1",
        "symbol": "AAPL",
        "timeframe": "1d",
        "dataset_fingerprint": "a" * 64,
        "engine_version": "engine-1",
        "validation_profile": gate.VALIDATION_PROFILE,
        "state": "APPROVED_FOR_PAPER",
        "version": 5,
        "evidence_version": 1,
        "created_at": "2026-08-03T03:00:00+00:00",
        "updated_at": "2026-08-03T04:55:00+00:00",
        "expires_at": "2026-08-04T05:00:00+00:00",
    }
    value.update(updates)
    return value


def test_adapter_dictionary_conversion_branches():
    assert adapter_module._as_dict({"value": 1}) == {"value": 1}
    assert adapter_module._as_dict(SampleModel(value=2)) == {"value": 2}
    assert adapter_module._as_dict(DuckModel()) == {"value": 3}
    assert adapter_module._as_dict(object()) == {}


@pytest.mark.asyncio
async def test_exact_lookup_builds_optional_age_query_and_rejects_empty_data():
    client = AdapterClient(data=exact_promotion())
    adapter = PromotionDatabaseAdapter(client)
    result = await adapter.get_latest_exact(
        account_id=1,
        symbol="aapl",
        strategy_id="strategy-1",
        timeframe="1d",
        correlation_id="corr-1",
        max_age_hours=0,
    )
    assert result["promotion_id"] == "promotion-1"
    params = client.get_calls[0][2]["params"]
    assert params["symbol"] == "AAPL"
    assert "max_age_hours" not in params

    client.data = None
    with pytest.raises(PromotionAuthorityError, match="no exact promotion"):
        await adapter.get_latest_exact(
            account_id=1,
            symbol="AAPL",
            strategy_id="strategy-1",
            timeframe="1d",
            correlation_id="corr-2",
            max_age_hours=0.2,
        )
    assert client.get_calls[1][2]["params"]["max_age_hours"] == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"promotion_id": ""}, "identity is incomplete"),
        ({"run_id": ""}, "identity is incomplete"),
        ({"state": "VALIDATED"}, "requires ROBUSTNESS_PASSED"),
        ({"version": "4"}, "version is invalid"),
        ({"evidence_version": None}, "evidence_version is invalid"),
    ],
)
async def test_approval_adapter_rejects_malformed_authority(
    monkeypatch,
    updates,
    message,
):
    monkeypatch.setenv("BACKTEST_PROMOTION_APPROVAL_TOKEN", "secret")
    adapter = PromotionDatabaseAdapter(AdapterClient())
    with pytest.raises(PromotionAuthorityError, match=message):
        await adapter.approve_for_paper(
            exact_promotion(state="ROBUSTNESS_PASSED", version=4, **updates),
            correlation_id="corr-1",
        )


@pytest.mark.asyncio
async def test_approval_adapter_rejects_unexpected_transition_result(monkeypatch):
    monkeypatch.setenv("BACKTEST_PROMOTION_APPROVAL_TOKEN", "secret")
    client = AdapterClient(
        approved=exact_promotion(state="ROBUSTNESS_PASSED", version=4)
    )
    adapter = PromotionDatabaseAdapter(client)
    with pytest.raises(PromotionAuthorityError, match="did not return"):
        await adapter.approve_for_paper(
            exact_promotion(state="ROBUSTNESS_PASSED", version=4),
            correlation_id="corr-1",
        )


def test_environment_symbol_and_timestamp_helpers(monkeypatch):
    monkeypatch.delenv("PROMOTION_BOOL", raising=False)
    assert gate._env_bool("PROMOTION_BOOL", True) is True
    monkeypatch.setenv("PROMOTION_BOOL", "YES")
    assert gate._env_bool("PROMOTION_BOOL") is True
    monkeypatch.setenv("PROMOTION_BOOL", "off")
    assert gate._env_bool("PROMOTION_BOOL", True) is False

    assert gate._symbol({"ticker": "aapl"}) == "AAPL"
    assert gate._symbol(SimpleNamespace(symbol="msft")) == "MSFT"
    assert gate._parse_timestamp("not-a-time") is None
    naive = gate._parse_timestamp("2026-08-03T05:00:00")
    assert naive is not None and naive.tzinfo == timezone.utc
    assert gate._parse_timestamp(NOW) == NOW
    assert gate._promotion_timestamp({}) == datetime.min.replace(
        tzinfo=timezone.utc
    )


def test_strategy_and_account_resolution_branches(monkeypatch):
    monkeypatch.setattr(config, "BACKTEST_MULTI_STRATEGY_GATE_ENABLED", False)
    assert gate._strategy_ids("primary", None) == ["primary"]
    assert gate._strategy_ids("primary", ["", "one", "one", "two"]) == [
        "one",
        "two",
    ]
    assert gate._strategy_ids("primary", []) == ["primary"]

    assert gate._resolve_account_id("9", []) == "9"
    assert gate._resolve_account_id(None, [{"account_id": "2"}]) == "2"
    assert gate._resolve_account_id(
        None,
        [{"account_id": "2"}, {"account_id": "3"}],
    ) == str(config.DEFAULT_ACCOUNT_ID)


def test_decision_rejects_malformed_unknown_and_missing_timestamps():
    malformed = exact_promotion(
        promotion_id="",
        run_id="",
        version="5",
        evidence_version=None,
        state="UNKNOWN",
        updated_at=None,
        created_at=None,
    )
    decision = gate._decision(
        promotion=malformed,
        lookup_error=None,
        account_id="1",
        symbol="AAPL",
        skill_id="skill-1",
        strategy_id="strategy-1",
        timeframe="1d",
        max_age_hours=26,
        now=NOW,
        auto_approve=False,
    )
    assert set(decision["rejection_codes"]) >= {
        "backtest_promotion_identity_missing",
        "backtest_promotion_version_invalid",
        "backtest_promotion_evidence_version_invalid",
        "backtest_promotion_timestamp_missing",
        "backtest_promotion_state_invalid",
    }

    empty = gate._decision(
        promotion={},
        lookup_error="database unavailable",
        account_id="1",
        symbol="AAPL",
        skill_id="skill-1",
        strategy_id="strategy-1",
        timeframe="1d",
        max_age_hours=26,
        now=NOW,
        auto_approve=False,
    )
    assert empty["rejection_codes"] == [
        "backtest_promotion_lookup_failed",
        "backtest_promotion_not_found",
    ]


class GateClient(AdapterClient):
    def __init__(self, records=None, error=None):
        super().__init__()
        self.records = list(records or [])
        self.error = error

    async def _get(self, path, correlation_id, **kwargs):
        self.get_calls.append((path, correlation_id, kwargs))
        if self.error is not None:
            raise self.error
        data = self.records.pop(0) if self.records else None
        return {"status": "success", "data": data}


@pytest.mark.asyncio
async def test_404_is_not_promoted_to_database_failure():
    error = RuntimeError("404 Not Found")
    error.response = SimpleNamespace(status_code=404)
    client = GateClient(error=error)
    result = await gate.filter_candidates_with_promotion_gate(
        db_client=client,
        selected_positions=[{"symbol": "AAPL"}],
        position_analysis_payloads=[{"symbol": "AAPL"}],
        correlation_id="corr-1",
        required=True,
        skill_id="skill-1",
        strategy_id="strategy-1",
        strategy_ids=["strategy-1"],
        timeframe="1d",
        max_age_hours=26,
        now=NOW,
        account_id="1",
        auto_approve=False,
    )
    codes = result["decisions"][0]["rejection_codes"]
    assert codes == ["backtest_promotion_not_found"]


@pytest.mark.asyncio
async def test_multi_strategy_selects_newest_approved_promotion():
    older = exact_promotion(
        strategy_id="strategy-old",
        promotion_id="promotion-old",
        updated_at="2026-08-03T03:00:00+00:00",
    )
    newer = exact_promotion(
        strategy_id="strategy-new",
        promotion_id="promotion-new",
        updated_at="2026-08-03T04:59:00+00:00",
    )
    client = GateClient(records=[older, newer])
    result = await gate.filter_candidates_with_promotion_gate(
        db_client=client,
        selected_positions=[{"symbol": "AAPL"}],
        position_analysis_payloads=[{"ticker": "AAPL"}],
        correlation_id="corr-1",
        required=True,
        skill_id="skill-1",
        strategy_id="strategy-old",
        strategy_ids=["strategy-old", "strategy-new"],
        timeframe="1d",
        max_age_hours=26,
        now=NOW,
        account_id="1",
        auto_approve=False,
    )
    assert result["decisions"][0]["selected_strategy_id"] == "strategy-new"
    assert result["strategy_ids_by_symbol"] == {"AAPL": "strategy-new"}


@pytest.mark.asyncio
async def test_empty_candidate_set_is_safe_and_performs_no_lookup():
    client = GateClient()
    result = await gate.filter_candidates_with_promotion_gate(
        db_client=client,
        selected_positions=[],
        position_analysis_payloads=[],
        correlation_id="corr-1",
        required=True,
        skill_id="skill-1",
        strategy_id="strategy-1",
        timeframe="1d",
        max_age_hours=26,
        now=NOW,
        account_id="1",
        auto_approve=False,
    )
    assert result["summary"] == {
        "candidate_count": 0,
        "allowed_count": 0,
        "rejected_count": 0,
    }
    assert client.get_calls == []

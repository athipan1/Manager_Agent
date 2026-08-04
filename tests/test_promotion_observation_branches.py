from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app import config
from app.services import backtest_gate_facade as facade
from app.services import promotion_paper_observer as observer
from app.services.promotion_database_adapter import (
    PromotionAuthorityError,
    PromotionDatabaseAdapter,
)


NOW = datetime(2026, 8, 4, tzinfo=timezone.utc)


class SampleModel(BaseModel):
    value: int


class DuckModel:
    def model_dump(self, mode="json"):
        return {"value": 2}


class LegacyDuck:
    def dict(self):
        return {"value": 3}


class AdapterClient:
    def __init__(self, data=None):
        self.data = data
        self.posts = []
        self.gets = []

    async def _post(
        self,
        path,
        correlation_id,
        json_data,
        extra_headers=None,
        **kwargs,
    ):
        self.posts.append((path, correlation_id, json_data, extra_headers))
        return {"status": "success", "data": self.data}

    async def _get(self, path, correlation_id, **kwargs):
        self.gets.append((path, correlation_id, kwargs))
        return {"status": "success", "data": self.data}

    def validate_standard_response(self, response):
        return SimpleNamespace(data=response["data"])


def observation(**updates):
    value = {
        "observation_id": "observation-1",
        "promotion_id": "promotion-1",
        "observation_key": "key-1",
        "to_state": "PAPER_OBSERVING",
        "to_version": 6,
    }
    value.update(updates)
    return value


def observe_kwargs(**updates):
    value = {
        "promotion_id": "promotion-1",
        "expected_state": "APPROVED_FOR_PAPER",
        "expected_version": 5,
        "observation_key": "key-1",
        "observed_at": "2026-08-04T00:00:00Z",
        "paper_drawdown_pct": 0.0,
        "reconciliation_ok": True,
        "duplicate_order_count": 0,
        "broker_order_count": 0,
        "database_order_count": 0,
        "filled_order_count": 0,
        "strategy_drift": False,
        "emergency_halt": False,
        "correlation_id": "corr-1",
    }
    value.update(updates)
    return value


def decision(**updates):
    value = {
        "symbol": "AAPL",
        "allowed": True,
        "rejection_codes": [],
        "strategy_id": "strategy-1",
        "selected_strategy_id": "strategy-1",
        "promotion_id": "promotion-1",
        "promotion_state": "APPROVED_FOR_PAPER",
        "promotion_version": 5,
    }
    value.update(updates)
    return value


def gate_result(**updates):
    value = {
        "account_id": "1",
        "selected_positions": [{"symbol": "AAPL"}],
        "position_analysis_payloads": [
            {"symbol": "AAPL", "strategy_id": "strategy-1"}
        ],
        "decisions": [decision()],
        "rejected": [],
        "summary": {
            "candidate_count": 1,
            "allowed_count": 1,
            "rejected_count": 0,
        },
    }
    value.update(updates)
    return value


def valid_reconciliation():
    return {
        "ok": True,
        "reconciled_at": "2026-08-04T00:00:00Z",
        "broker_state": {
            "captured_at": "2026-08-04T00:00:00Z",
            "open_orders": [],
            "positions": [],
        },
        "database_sync": {"status": "success"},
    }


class Execution:
    def __init__(self, data=None):
        self.data = data if data is not None else valid_reconciliation()
        self.entered = 0
        self.exited = 0

    async def __aenter__(self):
        self.entered += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.exited += 1

    async def reconcile_broker_state(self, *args, **kwargs):
        return SimpleNamespace(data=self.data)


class Database(AdapterClient):
    def __init__(self, data=None, orders=None, order_error=None):
        super().__init__(data=data or observation())
        self.orders = orders or []
        self.order_error = order_error

    async def get_orders(self, *args, **kwargs):
        if self.order_error:
            raise self.order_error
        return self.orders


@pytest.fixture(autouse=True)
def safe_environment(monkeypatch):
    monkeypatch.setattr(config, "TRADING_MODE", "PAPER")
    monkeypatch.setattr(config, "ALLOW_LIVE_TRADING", False)
    monkeypatch.setattr(config, "MANAGER_EMERGENCY_HALT", False)
    monkeypatch.setenv("BACKTEST_PROMOTION_APPROVAL_TOKEN", "secret")


def test_observer_conversion_and_collection_helpers():
    assert observer._as_dict({"value": 1}) == {"value": 1}
    assert observer._as_dict(SampleModel(value=1)) == {"value": 1}
    assert observer._as_dict(DuckModel()) == {"value": 2}
    assert observer._as_dict(LegacyDuck()) == {"value": 3}
    assert observer._as_dict(object()) == {}

    assert observer._rows(None) == []
    assert observer._rows({"orders": [{"symbol": "AAPL"}]}) == [
        {"symbol": "AAPL"}
    ]
    assert observer._rows([{"symbol": "AAPL"}]) == [{"symbol": "AAPL"}]
    assert observer._rows({"symbol": "AAPL"}) == [{"symbol": "AAPL"}]
    assert observer._symbol({"ticker": "msft"}) == "MSFT"
    assert observer._status({"order_status": "OPEN"}) == "open"


def test_order_identity_duplicate_and_active_helpers():
    rows = [
        {"order_id": "one", "status": "open"},
        {"order_id": "one", "status": "submitted"},
        {"client_order_id": "two", "status": "filled"},
        {"status": "open"},
    ]
    active = observer._active_orders(rows)
    assert len(active) == 3
    assert observer._order_identity(rows[0]) == "one"
    assert observer._order_identity(rows[2]) == "two"
    assert observer._order_identity(rows[3]) == ""
    identities, missing = observer._identity_set(active)
    assert identities == {"one"}
    assert missing == 1
    assert observer._duplicate_count(rows) == 1


def test_timestamp_float_drawdown_and_strategy_helpers():
    assert observer._parse_timestamp(None) is None
    assert observer._parse_timestamp("bad") is None
    assert observer._parse_timestamp("2026-08-04T00:00:00") is None
    assert observer._parse_timestamp("2026-08-04T00:00:00Z") == NOW
    assert observer._parse_timestamp(NOW) == NOW
    assert observer._iso_timestamp(NOW).endswith("Z")

    assert observer._float("bad") == 0.0
    assert observer._float(float("nan")) == 0.0
    assert observer._float(float("inf")) == 0.0
    assert observer._float("2.5") == 2.5
    assert observer._paper_drawdown_pct("MSFT", []) == 0.0
    assert observer._paper_drawdown_pct(
        "AAPL",
        [
            {
                "symbol": "AAPL",
                "unrealized_pnl": "-5",
                "avg_entry_price": "10",
                "qty": "5",
            }
        ],
    ) == pytest.approx(0.1)

    assert observer._strategy_drift({}, []) is True
    assert observer._strategy_drift(
        decision(),
        [{"symbol": "AAPL"}],
    ) is False
    assert observer._strategy_drift(
        decision(),
        [{"symbol": "AAPL", "strategy_id": "other"}],
    ) is True


def test_reconciliation_contract_and_error_merge_helpers():
    broker_state, reconciled_at, error = (
        observer._validate_reconciliation_contract(valid_reconciliation())
    )
    assert error is None
    assert reconciled_at == NOW
    assert broker_state["open_orders"] == []

    _, _, invalid_error = observer._validate_reconciliation_contract({})
    assert "reconciliation_timestamp_missing_or_invalid" in invalid_error
    assert "broker_state_missing_or_invalid" in invalid_error
    assert "broker_database_sync_not_successful" in invalid_error
    assert "broker_reconciliation_not_ok" in invalid_error
    assert observer._merge_reconciliation_error(None, None) is None
    assert observer._merge_reconciliation_error("first", "second") == (
        "first;second"
    )


def test_reconciliation_helper_detects_exact_missing_and_duplicates():
    exact = observer._reconciliation_for_symbol(
        symbol="AAPL",
        reconciliation_ok=True,
        broker_orders=[{"symbol": "AAPL", "order_id": "one"}],
        database_orders=[{"symbol": "AAPL", "order_id": "one"}],
    )
    assert exact["reconciliation_ok"] is True

    missing = observer._reconciliation_for_symbol(
        symbol="AAPL",
        reconciliation_ok=True,
        broker_orders=[{"symbol": "AAPL"}],
        database_orders=[{"symbol": "AAPL"}],
    )
    assert missing["reconciliation_ok"] is False
    assert missing["broker_missing_identity_count"] == 1

    duplicate = observer._reconciliation_for_symbol(
        symbol="AAPL",
        reconciliation_ok=True,
        broker_orders=[
            {"symbol": "AAPL", "order_id": "one"},
            {"symbol": "AAPL", "order_id": "one"},
        ],
        database_orders=[{"symbol": "AAPL", "order_id": "one"}],
    )
    assert duplicate["duplicate_order_count"] == 1
    assert duplicate["reconciliation_ok"] is False


def test_observation_key_and_enrichment_are_deterministic():
    first = observer._observation_key(
        account_id="1",
        promotion_id="promotion-1",
        correlation_id="corr-1",
    )
    assert first == observer._observation_key(
        account_id="1",
        promotion_id="promotion-1",
        correlation_id="corr-1",
    )
    assert first != observer._observation_key(
        account_id="1",
        promotion_id="promotion-1",
        correlation_id="corr-2",
    )
    rows = observer._enrich_rows(
        [{"symbol": "AAPL"}, {"symbol": "MSFT"}],
        {"AAPL": observation()},
    )
    assert rows[0]["promotion_observation_id"] == "observation-1"
    assert "promotion_id" not in rows[1]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"expected_state": "ROBUSTNESS_PASSED"}, "approved or observing"),
        ({"promotion_id": ""}, "identity is incomplete"),
        ({"expected_version": 0}, "identity is incomplete"),
        ({"observation_key": ""}, "identity is incomplete"),
    ],
)
async def test_observation_adapter_rejects_invalid_requests(updates, message):
    adapter = PromotionDatabaseAdapter(AdapterClient(data=observation()))
    arguments = observe_kwargs(**updates)
    with pytest.raises(PromotionAuthorityError, match=message):
        await adapter.observe_for_paper(**arguments)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "message"),
    [
        (observation(promotion_id="other"), "wrong observed promotion"),
        (observation(observation_key="other"), "wrong observation identity"),
        (observation(to_state="APPROVED_FOR_PAPER"), "invalid observation state"),
        (observation(to_version="6"), "invalid observation version"),
    ],
)
async def test_observation_adapter_rejects_invalid_responses(data, message):
    adapter = PromotionDatabaseAdapter(AdapterClient(data=data))
    with pytest.raises(PromotionAuthorityError, match=message):
        await adapter.observe_for_paper(**observe_kwargs())


@pytest.mark.asyncio
async def test_observation_adapter_lists_and_validates_ledger():
    adapter = PromotionDatabaseAdapter(AdapterClient(data=[observation()]))
    records = await adapter.list_observations(
        promotion_id="promotion-1",
        correlation_id="corr-list",
    )
    assert records[0]["observation_id"] == "observation-1"

    invalid = PromotionDatabaseAdapter(AdapterClient(data={"bad": True}))
    with pytest.raises(PromotionAuthorityError, match="invalid observation ledger"):
        await invalid.list_observations(
            promotion_id="promotion-1",
            correlation_id="corr-list-invalid",
        )


@pytest.mark.asyncio
async def test_owned_execution_client_and_database_error_fail_closed(monkeypatch):
    execution = Execution()
    monkeypatch.setattr(observer, "ExecutionAgentClient", lambda: execution)
    database = Database(
        data=observation(to_state="REVOKED"),
        order_error=RuntimeError("database unavailable"),
    )
    result = await observer.observe_promotion_gate_result(
        db_client=database,
        gate_result=gate_result(),
        account_id="1",
        correlation_id="corr-owned",
    )
    assert execution.entered == 1
    assert execution.exited == 1
    assert result["summary"]["allowed_count"] == 0
    assert database.posts[0][2]["reconciliation_ok"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_decision",
    [
        decision(promotion_id=""),
        decision(promotion_state="ROBUSTNESS_PASSED"),
    ],
)
async def test_invalid_promotion_identity_or_state_blocks_without_write(bad_decision):
    database = Database()
    result = await observer.observe_promotion_gate_result(
        db_client=database,
        gate_result=gate_result(decisions=[bad_decision]),
        account_id="1",
        correlation_id="corr-invalid",
        execution_client=Execution(),
    )
    assert result["summary"]["allowed_count"] == 0
    assert database.posts == []


@pytest.mark.asyncio
async def test_observation_write_error_and_nonterminal_state_block():
    database = Database()

    async def fail(*args, **kwargs):
        raise RuntimeError("write failed")

    database._post = fail
    failed = await observer.observe_promotion_gate_result(
        db_client=database,
        gate_result=gate_result(),
        account_id="1",
        correlation_id="corr-write-fail",
        execution_client=Execution(),
    )
    assert "paper_observation_write_failed" in (
        failed["decisions"][0]["rejection_codes"]
    )

    nonterminal = Database(data=observation(to_state="APPROVED_FOR_PAPER"))
    blocked = await observer.observe_promotion_gate_result(
        db_client=nonterminal,
        gate_result=gate_result(),
        account_id="1",
        correlation_id="corr-nonauthorized",
        execution_client=Execution(),
    )
    assert "paper_observation_not_authorized" in (
        blocked["decisions"][0]["rejection_codes"]
    )


def test_facade_observation_configuration_branches(monkeypatch):
    monkeypatch.delenv("BACKTEST_PROMOTION_OBSERVATION_REQUIRED", raising=False)
    monkeypatch.setenv("APP_ENV", "development")
    assert facade._observation_required(None, authority_required=True) is False
    monkeypatch.setenv("APP_ENV", "production")
    assert facade._observation_required(None, authority_required=True) is True
    monkeypatch.setenv("BACKTEST_PROMOTION_OBSERVATION_REQUIRED", "off")
    assert facade._observation_required(None, authority_required=True) is False
    assert facade._observation_required(True, authority_required=False) is True

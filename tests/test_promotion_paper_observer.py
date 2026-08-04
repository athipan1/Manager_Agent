from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

import pytest

from app import config
from app.services import backtest_gate_facade as facade
from app.services import promotion_paper_observer as observer
from app.services.promotion_database_adapter import (
    PromotionAuthorityError,
    PromotionDatabaseAdapter,
)


OBSERVED_AT = "2026-08-04T00:00:00Z"


def promotion_decision(**updates):
    value = {
        "symbol": "AAPL",
        "allowed": True,
        "rejection_codes": [],
        "account_id": "1",
        "skill_id": "hourly-sma-crossover",
        "strategy_id": "trend-following-balanced-v1",
        "selected_strategy_id": "trend-following-balanced-v1",
        "promotion_id": "promotion-1",
        "promotion_state": "APPROVED_FOR_PAPER",
        "promotion_version": 5,
        "evidence_version": 1,
        "latest_run_id": "run-1",
        "authority": "database-agent-backtest-promotion",
        "requires_risk_approval": True,
        "broker_boundary": "execution-agent-only",
    }
    value.update(updates)
    return value


def gate_result(**updates):
    decision = promotion_decision()
    value = {
        "status": "required",
        "required": True,
        "account_id": "1",
        "selected_positions": [{"symbol": "AAPL", "quantity": 10}],
        "position_analysis_payloads": [
            {
                "symbol": "AAPL",
                "strategy_id": "trend-following-balanced-v1",
            }
        ],
        "decisions": [decision],
        "rejected": [],
        "summary": {
            "candidate_count": 1,
            "allowed_count": 1,
            "rejected_count": 0,
        },
    }
    value.update(updates)
    return value


def reconciliation_data(
    *,
    open_orders=None,
    positions=None,
    ok=True,
    database_sync_status="success",
):
    return {
        "ok": ok,
        "reconciled_at": OBSERVED_AT,
        "broker_state": {
            "captured_at": OBSERVED_AT,
            "open_orders": list(open_orders or []),
            "positions": list(positions or []),
        },
        "database_sync": {"status": database_sync_status},
    }


class FakeExecutionClient:
    def __init__(self, *, data=None, error=None):
        self.data = data if data is not None else reconciliation_data()
        self.error = error
        self.calls = []
        self.entered = 0
        self.exited = 0

    async def __aenter__(self):
        self.entered += 1
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.exited += 1

    async def reconcile_broker_state(
        self,
        account_id,
        correlation_id,
        *,
        push_to_database=None,
    ):
        self.calls.append((account_id, correlation_id, push_to_database))
        if self.error:
            raise self.error
        return SimpleNamespace(data=deepcopy(self.data))


class FakeDatabaseClient:
    def __init__(
        self,
        *,
        orders=None,
        observation_state="PAPER_OBSERVING",
        observation_error=None,
    ):
        self.orders = list(orders or [])
        self.observation_state = observation_state
        self.observation_error = observation_error
        self.posts = []
        self.get_order_calls = []

    async def get_orders(self, account_id, correlation_id):
        self.get_order_calls.append((account_id, correlation_id))
        return deepcopy(self.orders)

    async def _post(
        self,
        path,
        correlation_id,
        json_data,
        extra_headers=None,
        **kwargs,
    ):
        self.posts.append(
            {
                "path": path,
                "correlation_id": correlation_id,
                "json": deepcopy(json_data),
                "extra_headers": deepcopy(extra_headers),
            }
        )
        if self.observation_error:
            raise self.observation_error
        data = {
            "observation_id": "promotion-observation-1",
            "promotion_id": "promotion-1",
            "observation_key": json_data["observation_key"],
            "action": (
                "START_OBSERVING"
                if json_data["expected_state"] == "APPROVED_FOR_PAPER"
                else "HEARTBEAT"
            ),
            "reason_code": "paper_observation_started",
            "from_state": json_data["expected_state"],
            "to_state": self.observation_state,
            "from_version": json_data["expected_version"],
            "to_version": json_data["expected_version"] + 1,
            "observed_at": json_data["observed_at"],
            "created_at": json_data["observed_at"],
            "correlation_id": correlation_id,
            "paper_drawdown_pct": json_data["paper_drawdown_pct"],
            "reconciliation_ok": json_data["reconciliation_ok"],
            "duplicate_order_count": json_data["duplicate_order_count"],
            "broker_order_count": json_data["broker_order_count"],
            "database_order_count": json_data["database_order_count"],
            "filled_order_count": json_data["filled_order_count"],
            "strategy_drift": json_data["strategy_drift"],
            "emergency_halt": json_data["emergency_halt"],
            "metadata": json_data["metadata"],
            "promotion": {
                "promotion_id": "promotion-1",
                "state": self.observation_state,
                "version": json_data["expected_version"] + 1,
            },
            "idempotent_replay": False,
        }
        return {"status": "success", "data": data}

    async def _get(self, path, correlation_id, **kwargs):
        return {"status": "success", "data": []}

    def validate_standard_response(self, response):
        return SimpleNamespace(data=response.get("data"))


@pytest.fixture(autouse=True)
def paper_safety(monkeypatch):
    monkeypatch.setattr(config, "TRADING_MODE", "PAPER")
    monkeypatch.setattr(config, "ALLOW_LIVE_TRADING", False)
    monkeypatch.setattr(config, "MANAGER_EMERGENCY_HALT", False)
    monkeypatch.setenv("BACKTEST_PROMOTION_APPROVAL_TOKEN", "observation-secret")


@pytest.mark.asyncio
async def test_healthy_observation_is_required_before_risk_and_enriches_payloads():
    database = FakeDatabaseClient()
    execution = FakeExecutionClient()

    result = await observer.observe_promotion_gate_result(
        db_client=database,
        gate_result=gate_result(),
        account_id="1",
        correlation_id="corr-healthy",
        execution_client=execution,
    )

    assert result["summary"]["allowed_count"] == 1
    assert result["paper_observation"]["reconciliation_ok"] is True
    assert result["decisions"][0]["paper_observation"]["to_state"] == (
        "PAPER_OBSERVING"
    )
    assert result["selected_positions"][0]["promotion_id"] == "promotion-1"
    assert result["selected_positions"][0]["promotion_observation_id"] == (
        "promotion-observation-1"
    )
    assert result["position_analysis_payloads"][0]["promotion_state"] == (
        "PAPER_OBSERVING"
    )
    assert execution.calls == [("1", "corr-healthy", True)]
    call = database.posts[0]
    assert call["path"] == "/backtests/promotion-observations/promotion-1"
    assert call["extra_headers"] == {
        "X-PROMOTION-APPROVAL-KEY": "observation-secret"
    }
    assert call["json"]["reconciliation_ok"] is True
    assert call["json"]["metadata"]["requires_risk_approval"] is True


@pytest.mark.asyncio
async def test_same_correlation_produces_same_observation_key_for_retry():
    database = FakeDatabaseClient()
    execution = FakeExecutionClient()

    first = await observer.observe_promotion_gate_result(
        db_client=database,
        gate_result=gate_result(),
        account_id="1",
        correlation_id="corr-replay",
        execution_client=execution,
    )
    second = await observer.observe_promotion_gate_result(
        db_client=database,
        gate_result=gate_result(),
        account_id="1",
        correlation_id="corr-replay",
        execution_client=execution,
    )

    assert first["decisions"][0]["observation_key"] == (
        second["decisions"][0]["observation_key"]
    )
    assert database.posts[0]["json"]["observation_key"] == (
        database.posts[1]["json"]["observation_key"]
    )


@pytest.mark.asyncio
async def test_order_identity_mismatch_revokes_and_blocks_candidate():
    database = FakeDatabaseClient(
        orders=[
            {
                "symbol": "AAPL",
                "status": "open",
                "order_id": "database-order-1",
            }
        ],
        observation_state="REVOKED",
    )
    execution = FakeExecutionClient(
        data=reconciliation_data(
            open_orders=[
                {
                    "symbol": "AAPL",
                    "status": "open",
                    "order_id": "broker-order-1",
                }
            ]
        )
    )

    result = await observer.observe_promotion_gate_result(
        db_client=database,
        gate_result=gate_result(),
        account_id="1",
        correlation_id="corr-mismatch",
        execution_client=execution,
    )

    assert result["summary"]["allowed_count"] == 0
    assert result["selected_positions"] == []
    assert set(result["decisions"][0]["rejection_codes"]) >= {
        "paper_observation_reconciliation_failed",
        "paper_observation_terminal",
    }
    assert database.posts[0]["json"]["reconciliation_ok"] is False
    assert database.posts[0]["json"]["broker_order_count"] == 1
    assert database.posts[0]["json"]["database_order_count"] == 1


@pytest.mark.asyncio
async def test_emergency_halt_is_propagated_and_blocks_candidate(monkeypatch):
    monkeypatch.setattr(config, "MANAGER_EMERGENCY_HALT", True)
    database = FakeDatabaseClient(observation_state="REVOKED")

    result = await observer.observe_promotion_gate_result(
        db_client=database,
        gate_result=gate_result(),
        account_id="1",
        correlation_id="corr-halt",
        execution_client=FakeExecutionClient(),
    )

    assert result["summary"]["allowed_count"] == 0
    assert database.posts[0]["json"]["emergency_halt"] is True
    assert "paper_observation_terminal" in (
        result["decisions"][0]["rejection_codes"]
    )


@pytest.mark.asyncio
async def test_paper_drawdown_is_calculated_and_terminal_result_blocks():
    database = FakeDatabaseClient(observation_state="REVOKED")
    execution = FakeExecutionClient(
        data=reconciliation_data(
            positions=[
                {
                    "symbol": "AAPL",
                    "unrealized_pl": "-20",
                    "cost_basis": "100",
                }
            ]
        )
    )

    result = await observer.observe_promotion_gate_result(
        db_client=database,
        gate_result=gate_result(),
        account_id="1",
        correlation_id="corr-drawdown",
        execution_client=execution,
    )

    assert database.posts[0]["json"]["paper_drawdown_pct"] == pytest.approx(0.2)
    assert result["summary"]["allowed_count"] == 0


@pytest.mark.asyncio
async def test_reconciliation_failure_is_written_as_fail_closed_observation():
    database = FakeDatabaseClient(observation_state="REVOKED")
    execution = FakeExecutionClient(error=RuntimeError("broker unavailable"))

    result = await observer.observe_promotion_gate_result(
        db_client=database,
        gate_result=gate_result(),
        account_id="1",
        correlation_id="corr-error",
        execution_client=execution,
    )

    assert result["summary"]["allowed_count"] == 0
    assert database.posts[0]["json"]["reconciliation_ok"] is False
    assert "broker unavailable" in (
        database.posts[0]["json"]["metadata"]["reconciliation_error"]
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "error_code"),
    [
        (
            {
                "ok": True,
                "broker_state": {
                    "captured_at": OBSERVED_AT,
                    "open_orders": [],
                    "positions": [],
                },
                "database_sync": {"status": "success"},
            },
            "reconciliation_timestamp_missing_or_invalid",
        ),
        (
            {
                "ok": True,
                "reconciled_at": OBSERVED_AT,
                "database_sync": {"status": "success"},
            },
            "broker_state_missing_or_invalid",
        ),
        (
            {
                "ok": True,
                "reconciled_at": OBSERVED_AT,
                "broker_state": {
                    "captured_at": OBSERVED_AT,
                    "open_orders": [],
                    "positions": [],
                },
                "database_sync": {"status": "skipped"},
            },
            "broker_database_sync_not_successful",
        ),
    ],
)
async def test_malformed_reconciliation_contract_is_written_fail_closed(
    data,
    error_code,
):
    database = FakeDatabaseClient(observation_state="REVOKED")
    result = await observer.observe_promotion_gate_result(
        db_client=database,
        gate_result=gate_result(),
        account_id="1",
        correlation_id="corr-malformed",
        execution_client=FakeExecutionClient(data=data),
    )

    assert result["summary"]["allowed_count"] == 0
    assert database.posts[0]["json"]["reconciliation_ok"] is False
    assert error_code in (
        database.posts[0]["json"]["metadata"]["reconciliation_error"]
    )


@pytest.mark.asyncio
async def test_missing_symbol_is_blocked_without_observation_write():
    database = FakeDatabaseClient()
    result = await observer.observe_promotion_gate_result(
        db_client=database,
        gate_result=gate_result(
            decisions=[promotion_decision(symbol="")],
            selected_positions=[],
            position_analysis_payloads=[],
        ),
        account_id="1",
        correlation_id="corr-no-symbol",
        execution_client=FakeExecutionClient(),
    )

    assert result["summary"]["allowed_count"] == 0
    assert database.posts == []
    assert "paper_observation_promotion_identity_invalid" in (
        result["decisions"][0]["rejection_codes"]
    )


@pytest.mark.asyncio
async def test_live_or_live_enabled_mode_is_rejected(monkeypatch):
    database = FakeDatabaseClient()
    execution = FakeExecutionClient()

    monkeypatch.setattr(config, "TRADING_MODE", "LIVE")
    with pytest.raises(observer.PromotionObservationError, match="PAPER"):
        await observer.observe_promotion_gate_result(
            db_client=database,
            gate_result=gate_result(),
            account_id="1",
            correlation_id="corr-live",
            execution_client=execution,
        )

    monkeypatch.setattr(config, "TRADING_MODE", "PAPER")
    monkeypatch.setattr(config, "ALLOW_LIVE_TRADING", True)
    with pytest.raises(observer.PromotionObservationError, match="false"):
        await observer.observe_promotion_gate_result(
            db_client=database,
            gate_result=gate_result(),
            account_id="1",
            correlation_id="corr-live-flag",
            execution_client=execution,
        )


@pytest.mark.asyncio
async def test_no_eligible_candidates_skips_execution_and_database():
    database = FakeDatabaseClient()
    execution = FakeExecutionClient()
    rejected = promotion_decision(
        allowed=False,
        rejection_codes=["backtest_promotion_expired"],
    )

    result = await observer.observe_promotion_gate_result(
        db_client=database,
        gate_result=gate_result(
            decisions=[rejected],
            selected_positions=[],
            position_analysis_payloads=[],
        ),
        account_id="1",
        correlation_id="corr-none",
        execution_client=execution,
    )

    assert result["paper_observation"]["status"] == "not_required"
    assert execution.calls == []
    assert database.posts == []


@pytest.mark.asyncio
async def test_observation_adapter_fails_closed_for_invalid_contract(monkeypatch):
    monkeypatch.delenv("BACKTEST_PROMOTION_APPROVAL_TOKEN", raising=False)
    adapter = PromotionDatabaseAdapter(FakeDatabaseClient())
    with pytest.raises(PromotionAuthorityError, match="APPROVAL_TOKEN"):
        await adapter.observe_for_paper(
            promotion_id="promotion-1",
            expected_state="APPROVED_FOR_PAPER",
            expected_version=5,
            observation_key="key-1",
            observed_at=OBSERVED_AT,
            paper_drawdown_pct=0.0,
            reconciliation_ok=True,
            duplicate_order_count=0,
            broker_order_count=0,
            database_order_count=0,
            filled_order_count=0,
            strategy_drift=False,
            emergency_halt=False,
            correlation_id="corr-adapter",
        )


@pytest.mark.asyncio
async def test_facade_invokes_observer_only_when_required(monkeypatch):
    promotion_result = gate_result()
    calls = []

    async def promotion_gate(**kwargs):
        return deepcopy(promotion_result)

    async def observe(**kwargs):
        calls.append(kwargs)
        return {**kwargs["gate_result"], "observed": True}

    monkeypatch.setattr(facade, "filter_candidates_with_promotion_gate", promotion_gate)
    monkeypatch.setattr(facade, "observe_promotion_gate_result", observe)

    disabled = await facade.filter_candidates_with_backtest_gate(
        db_client=object(),
        selected_positions=[{"symbol": "AAPL"}],
        position_analysis_payloads=[{"symbol": "AAPL"}],
        correlation_id="corr-facade-disabled",
        required=True,
        skill_id="skill-1",
        strategy_id="strategy-1",
        timeframe="1d",
        max_age_hours=26,
        promotion_authority_required=True,
        paper_observation_required=False,
        account_id="1",
    )
    enabled = await facade.filter_candidates_with_backtest_gate(
        db_client=object(),
        selected_positions=[{"symbol": "AAPL"}],
        position_analysis_payloads=[{"symbol": "AAPL"}],
        correlation_id="corr-facade-enabled",
        required=True,
        skill_id="skill-1",
        strategy_id="strategy-1",
        timeframe="1d",
        max_age_hours=26,
        promotion_authority_required=True,
        paper_observation_required=True,
        account_id="1",
        execution_client="execution-test-double",
    )

    assert disabled["paper_observation"]["status"] == "disabled"
    assert enabled["observed"] is True
    assert len(calls) == 1
    assert calls[0]["account_id"] == "1"
    assert calls[0]["execution_client"] == "execution-test-double"

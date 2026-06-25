from types import SimpleNamespace

import pytest

from app import config
from app.workflows.learning_workflow import (
    apply_learning_deltas_if_allowed,
    most_impactful_approved_trade,
    trigger_learning_cycle_if_allowed,
)


class PolicyDeltas:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self, exclude_none=True):
        if exclude_none:
            return {k: v for k, v in self.payload.items() if v is not None}
        return self.payload


class FakeLearningClient:
    response = None
    calls = []

    def __init__(self, db_client):
        self.db_client = db_client

    async def trigger_learning_cycle(self, **kwargs):
        self.__class__.calls.append(kwargs)
        return self.__class__.response


@pytest.fixture(autouse=True)
def reset_fake_learning_client():
    FakeLearningClient.response = None
    FakeLearningClient.calls = []


def test_apply_learning_deltas_no_response():
    assert apply_learning_deltas_if_allowed(None) == {
        "applied": False,
        "pending": False,
        "reason": "no_active_learning_delta",
    }


def test_apply_learning_deltas_warmup_response():
    response = SimpleNamespace(learning_state="warmup", policy_deltas=PolicyDeltas({"risk": 0.1}))

    assert apply_learning_deltas_if_allowed(response) == {
        "applied": False,
        "pending": False,
        "reason": "no_active_learning_delta",
    }


def test_apply_learning_deltas_empty_delta():
    response = SimpleNamespace(learning_state="active", policy_deltas=PolicyDeltas({}))

    assert apply_learning_deltas_if_allowed(response) == {
        "applied": False,
        "pending": False,
        "reason": "empty_learning_delta",
    }


def test_apply_learning_deltas_pending_when_auto_apply_disabled(monkeypatch):
    monkeypatch.setattr(config, "APPLY_LEARNING_DELTAS", False)
    response = SimpleNamespace(learning_state="active", policy_deltas=PolicyDeltas({"RISK_PER_TRADE": 0.02}))

    assert apply_learning_deltas_if_allowed(response) == {
        "applied": False,
        "pending": True,
        "reason": "approval_required",
    }


def test_apply_learning_deltas_applies_when_enabled(monkeypatch):
    monkeypatch.setattr(config, "APPLY_LEARNING_DELTAS", True)
    applied = []

    def fake_apply_deltas(deltas):
        applied.append(deltas)

    monkeypatch.setattr("app.workflows.learning_workflow.config_manager.apply_deltas", fake_apply_deltas)
    response = SimpleNamespace(learning_state="active", policy_deltas=PolicyDeltas({"RISK_PER_TRADE": 0.02, "EMPTY": None}))

    assert apply_learning_deltas_if_allowed(response) == {
        "applied": True,
        "pending": False,
        "reason": None,
    }
    assert applied == [{"RISK_PER_TRADE": 0.02}]


@pytest.mark.asyncio
async def test_trigger_learning_cycle_skips_dry_run(monkeypatch):
    monkeypatch.setattr("app.workflows.learning_workflow.LearningAgentClient", FakeLearningClient)

    result = await trigger_learning_cycle_if_allowed(
        db_client=object(),
        account_id=1,
        symbol="AAPL",
        correlation_id="cid",
        execution_result={"status": "dry_run"},
        dry_run=True,
    )

    assert result == {"applied": False, "pending": False, "reason": "dry_run"}
    assert FakeLearningClient.calls == []


@pytest.mark.asyncio
async def test_trigger_learning_cycle_calls_learning_client(monkeypatch):
    monkeypatch.setattr(config, "APPLY_LEARNING_DELTAS", False)
    monkeypatch.setattr("app.workflows.learning_workflow.LearningAgentClient", FakeLearningClient)
    FakeLearningClient.response = SimpleNamespace(
        learning_state="active",
        policy_deltas=PolicyDeltas({"RISK_PER_TRADE": 0.02}),
    )

    result = await trigger_learning_cycle_if_allowed(
        db_client=object(),
        account_id=1,
        symbol="AAPL",
        correlation_id="cid",
        execution_result={"status": "submitted"},
        dry_run=False,
    )

    assert result == {"applied": False, "pending": True, "reason": "approval_required"}
    assert FakeLearningClient.calls == [
        {
            "account_id": 1,
            "symbol": "AAPL",
            "correlation_id": "cid",
            "execution_result": {"status": "submitted"},
        }
    ]


def test_most_impactful_approved_trade_returns_highest_risk_amount():
    decisions = [
        {"symbol": "AAPL", "approved": True, "risk_amount": 10},
        {"symbol": "MSFT", "approved": False, "risk_amount": 100},
        {"symbol": "NVDA", "approved": True, "risk_amount": 25},
    ]

    assert most_impactful_approved_trade(decisions) == {
        "symbol": "NVDA",
        "approved": True,
        "risk_amount": 25,
    }


def test_most_impactful_approved_trade_returns_none_when_no_approved_trades():
    assert most_impactful_approved_trade([{"symbol": "AAPL", "approved": False}]) is None

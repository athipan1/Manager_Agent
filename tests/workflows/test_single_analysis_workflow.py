from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models import AgentRequestBody
from app.workflows.single_analysis_workflow import (
    execution_result_for_decision,
    manager_metadata,
    run_single_analysis_flow,
)


class FakeDbClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get_account_balance(self, account_id, correlation_id):
        return SimpleNamespace(cash_balance=Decimal("10000"))

    async def get_positions(self, account_id, correlation_id):
        return []


class FakeExecutionClient:
    calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def analysis_result(final_verdict="hold", status="complete"):
    return {
        "ticker": "AAPL",
        "final_verdict": final_verdict,
        "status": status,
        "details": SimpleNamespace(technical=None, fundamental=None),
        "raw_data": {},
    }


async def fake_fetch_context_value(db_client, account_id, correlation_id):
    return Decimal("0")


async def fake_fetch_session_risk_context(db_client, account_id, symbol, correlation_id):
    return {"trades_today": 0}


def test_manager_metadata_preserves_legacy_shape(monkeypatch):
    monkeypatch.setattr("app.workflows.single_analysis_workflow.config.TRADING_MODE", "PAPER")
    monkeypatch.setattr("app.workflows.single_analysis_workflow.config.TRADING_ENABLED", True)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.config.ALLOW_LIVE_TRADING", False)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.config.ASSET_CLASS", "stock")
    monkeypatch.setattr("app.workflows.single_analysis_workflow.config.MANUAL_APPROVAL_REQUIRED", True)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.config.APPLY_LEARNING_DELTAS", False)

    assert manager_metadata(
        risk_context_loaded=True,
        learning_delta_applied=False,
        learning_delta_pending=True,
        learning_delta_skipped_reason="approval_required",
        dry_run=True,
    ) == {
        "trading_mode": "PAPER",
        "trading_enabled": True,
        "allow_live_trading": False,
        "asset_class": "stock",
        "manual_approval_required": True,
        "risk_context_loaded": True,
        "learning_delta_auto_apply_enabled": False,
        "learning_delta_applied": False,
        "learning_delta_pending": True,
        "dry_run": True,
        "learning_delta_skipped_reason": "approval_required",
    }


def test_execution_result_for_decision_handles_non_submit_cases(monkeypatch):
    monkeypatch.setattr("app.workflows.single_analysis_workflow.config.MANUAL_APPROVAL_REQUIRED", False)

    assert execution_result_for_decision(trade_decision=None, dry_run=False) == {
        "status": "not_attempted",
        "reason": "No trade decision.",
    }

    assert execution_result_for_decision(
        trade_decision={"risk_approval_id": "risk-1"},
        dry_run=True,
    ) == {
        "status": "dry_run",
        "reason": "Execution skipped by dry-run mode.",
        "risk_approval_id": "risk-1",
    }

    assert execution_result_for_decision(
        trade_decision={"approved": False, "reason": "risk rejected", "risk_approval_id": "risk-2"},
        dry_run=False,
    ) == {
        "status": "rejected",
        "reason": "risk rejected",
        "risk_approval_id": "risk-2",
    }


def test_execution_result_for_decision_respects_manual_approval(monkeypatch):
    monkeypatch.setattr("app.workflows.single_analysis_workflow.config.MANUAL_APPROVAL_REQUIRED", True)

    assert execution_result_for_decision(
        trade_decision={"approved": True, "risk_approval_id": "risk-1"},
        dry_run=False,
    ) == {
        "status": "manual_approval_required",
        "reason": "Manual approval is required before live stock execution.",
        "risk_approval_id": "risk-1",
    }


@pytest.mark.asyncio
async def test_run_single_analysis_flow_dry_run_hold(monkeypatch):
    monkeypatch.setattr("app.workflows.single_analysis_workflow.DatabaseAgentClient", FakeDbClient)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.validate_stock_scope", lambda ticker: None)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.config_manager.get", lambda key: 1 if key == "DEFAULT_ACCOUNT_ID" else None)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.fetch_context_value", fake_fetch_context_value)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.fetch_session_risk_context", fake_fetch_session_risk_context)

    async def fake_analyze_single_asset(ticker, correlation_id):
        return analysis_result("hold")

    async def fake_persist_signal(*args, **kwargs):
        return None

    async def fake_audit_trade_decision(**kwargs):
        return {"report_id": kwargs["correlation_id"], "dry_run": kwargs["dry_run"], "execution": kwargs["execution_result"]}

    monkeypatch.setattr("app.workflows.single_analysis_workflow.analyze_single_asset", fake_analyze_single_asset)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.persist_signal", fake_persist_signal)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.audit_trade_decision", fake_audit_trade_decision)

    response = await run_single_analysis_flow(AgentRequestBody(ticker="AAPL"), dry_run=True)

    assert response.status == "success"
    assert response.metadata["dry_run"] is True
    assert response.metadata["learning_delta_skipped_reason"] == "dry_run"
    assert response.data["execution"] == {"status": "not_attempted", "reason": "No trade decision."}


@pytest.mark.asyncio
async def test_run_single_analysis_flow_executes_approved_trade(monkeypatch):
    monkeypatch.setattr("app.workflows.single_analysis_workflow.DatabaseAgentClient", FakeDbClient)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.ExecutionAgentClient", FakeExecutionClient)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.validate_stock_scope", lambda ticker: None)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.config.MANUAL_APPROVAL_REQUIRED", False)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.config_manager.get", lambda key: 1 if key == "DEFAULT_ACCOUNT_ID" else None)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.fetch_context_value", fake_fetch_context_value)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.fetch_session_risk_context", fake_fetch_session_risk_context)

    async def fake_analyze_single_asset(ticker, correlation_id):
        return analysis_result("buy")

    def fake_evaluate_single_trade_risk(**kwargs):
        return {"approved": True, "symbol": "AAPL", "risk_approval_id": "risk-1", "position_size": 1}

    async def fake_execute_trade(exec_client, trade_decision, account_id, correlation_id, db_client=None):
        return {"status": "submitted", "risk_approval_id": trade_decision["risk_approval_id"]}

    async def fake_persist_signal(*args, **kwargs):
        return None

    async def fake_audit_trade_decision(**kwargs):
        return {"report_id": kwargs["correlation_id"]}

    async def fake_trigger_learning_cycle_if_allowed(**kwargs):
        return {"applied": False, "pending": False, "reason": "no_learning_response"}

    monkeypatch.setattr("app.workflows.single_analysis_workflow.analyze_single_asset", fake_analyze_single_asset)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.evaluate_single_trade_risk", fake_evaluate_single_trade_risk)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.execute_trade", fake_execute_trade)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.persist_signal", fake_persist_signal)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.audit_trade_decision", fake_audit_trade_decision)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.trigger_learning_cycle_if_allowed", fake_trigger_learning_cycle_if_allowed)

    response = await run_single_analysis_flow(AgentRequestBody(ticker="AAPL"), dry_run=False)

    assert response.status == "success"
    assert response.data.final_verdict == "buy"
    assert response.metadata["dry_run"] is False


@pytest.mark.asyncio
async def test_run_single_analysis_flow_raises_500_when_agents_fail(monkeypatch):
    monkeypatch.setattr("app.workflows.single_analysis_workflow.DatabaseAgentClient", FakeDbClient)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.validate_stock_scope", lambda ticker: None)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.config_manager.get", lambda key: 1 if key == "DEFAULT_ACCOUNT_ID" else None)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.fetch_context_value", fake_fetch_context_value)
    monkeypatch.setattr("app.workflows.single_analysis_workflow.fetch_session_risk_context", fake_fetch_session_risk_context)

    async def fake_analyze_single_asset(ticker, correlation_id):
        return {"ticker": ticker, "error": "All agents failed", "raw_data": {}}

    monkeypatch.setattr("app.workflows.single_analysis_workflow.analyze_single_asset", fake_analyze_single_asset)

    with pytest.raises(HTTPException) as exc_info:
        await run_single_analysis_flow(AgentRequestBody(ticker="AAPL"), dry_run=False)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "All agents failed"

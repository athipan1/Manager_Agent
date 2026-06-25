from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models import MultiAgentRequestBody, ReportDetails
from app.workflows.multi_analysis_workflow import (
    execution_outcome_for_decision,
    run_multi_analysis_flow,
)


class FakeDbClient:
    saved_signals = []

    async def __aenter__(self):
        self.saved_signals = []
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get_account_balance(self, account_id, correlation_id):
        return SimpleNamespace(cash_balance=Decimal("10000"))

    async def get_positions(self, account_id, correlation_id):
        return []

    async def save_signal(self, **kwargs):
        self.saved_signals.append(kwargs)


def analysis_result(ticker, verdict="buy"):
    return {
        "ticker": ticker,
        "final_verdict": verdict,
        "status": "complete",
        "details": ReportDetails(technical=None, fundamental=None),
        "raw_data": {},
    }


def test_execution_outcome_for_decision_returns_rejected_payload():
    outcome = execution_outcome_for_decision(
        {"approved": False, "symbol": "AAPL", "reason": "risk rejected"},
        {},
    )

    assert outcome == {"status": "rejected", "reason": "risk rejected", "details": None}


def test_execution_outcome_for_decision_returns_manual_approval_fallback(monkeypatch):
    monkeypatch.setattr("app.workflows.multi_analysis_workflow.config.MANUAL_APPROVAL_REQUIRED", True)

    outcome = execution_outcome_for_decision(
        {"approved": True, "symbol": "AAPL", "risk_approval_id": "risk-1"},
        {},
    )

    assert outcome == {
        "status": "manual_approval_required",
        "reason": "Manual approval is required before live stock execution.",
        "risk_approval_id": "risk-1",
    }


@pytest.mark.asyncio
async def test_run_multi_analysis_flow_returns_multi_report_with_manual_approval(monkeypatch):
    monkeypatch.setattr("app.workflows.multi_analysis_workflow.DatabaseAgentClient", FakeDbClient)
    monkeypatch.setattr("app.workflows.multi_analysis_workflow.validate_stock_scope", lambda ticker: None)
    monkeypatch.setattr("app.workflows.multi_analysis_workflow.config_manager.get", lambda key: "default-account")
    monkeypatch.setattr("app.workflows.multi_analysis_workflow.config.MANUAL_APPROVAL_REQUIRED", True)

    async def fake_fetch_context_value(db_client, account_id, correlation_id):
        return Decimal("0")

    async def fake_fetch_session_risk_contexts(db_client, account_id, symbols, correlation_id):
        return {"trades_today": 0, "symbol_contexts": {symbol: {} for symbol in symbols}}

    async def fake_analyze_single_asset(ticker, correlation_id):
        return analysis_result(ticker, "buy")

    def fake_evaluate_portfolio_risk(**kwargs):
        return [
            {
                "approved": True,
                "symbol": "AAPL",
                "action": "buy",
                "position_size": 1,
                "risk_approval_id": "risk-aapl",
                "risk_amount": 10,
            },
            {
                "approved": False,
                "symbol": "MSFT",
                "action": "buy",
                "reason": "risk rejected",
                "position_size": 0,
            },
        ]

    audit_calls = []

    async def fake_audit_trade_decision(**kwargs):
        audit_calls.append(kwargs)
        return {"ok": True}

    async def fake_trigger_learning_cycle_if_allowed(**kwargs):
        return {"applied": False, "pending": False, "reason": "approval_required"}

    monkeypatch.setattr("app.workflows.multi_analysis_workflow.fetch_context_value", fake_fetch_context_value)
    monkeypatch.setattr("app.workflows.multi_analysis_workflow.fetch_session_risk_contexts", fake_fetch_session_risk_contexts)
    monkeypatch.setattr("app.workflows.multi_analysis_workflow.analyze_single_asset", fake_analyze_single_asset)
    monkeypatch.setattr("app.workflows.multi_analysis_workflow.evaluate_portfolio_risk", fake_evaluate_portfolio_risk)
    monkeypatch.setattr("app.workflows.multi_analysis_workflow.audit_trade_decision", fake_audit_trade_decision)
    monkeypatch.setattr("app.workflows.multi_analysis_workflow.trigger_learning_cycle_if_allowed", fake_trigger_learning_cycle_if_allowed)

    response = await run_multi_analysis_flow(MultiAgentRequestBody(tickers=["AAPL", "MSFT"]))

    assert response.status == "success"
    assert response.data.execution_summary.total_trades_approved == 1
    assert response.data.execution_summary.total_trades_executed == 0
    assert response.data.execution_summary.total_trades_failed == 1
    assert [result.analysis.ticker for result in response.data.results] == ["AAPL", "MSFT"]
    assert response.data.results[0].execution.status == "manual_approval_required"
    assert response.data.results[1].execution.status == "rejected"
    assert len(audit_calls) == 2
    assert response.metadata["learning_delta_skipped_reason"] == "approval_required"


@pytest.mark.asyncio
async def test_run_multi_analysis_flow_uses_execution_results_when_submitted(monkeypatch):
    monkeypatch.setattr("app.workflows.multi_analysis_workflow.DatabaseAgentClient", FakeDbClient)
    monkeypatch.setattr("app.workflows.multi_analysis_workflow.validate_stock_scope", lambda ticker: None)
    monkeypatch.setattr("app.workflows.multi_analysis_workflow.config_manager.get", lambda key: "default-account")

    async def fake_fetch_context_value(db_client, account_id, correlation_id):
        return Decimal("0")

    async def fake_fetch_session_risk_contexts(db_client, account_id, symbols, correlation_id):
        return {}

    async def fake_analyze_single_asset(ticker, correlation_id):
        return analysis_result(ticker, "buy")

    def fake_evaluate_portfolio_risk(**kwargs):
        return [
            {
                "approved": True,
                "symbol": "AAPL",
                "action": "buy",
                "position_size": 1,
                "risk_approval_id": "risk-aapl",
                "risk_amount": 10,
            }
        ]

    async def fake_execute_approved_trades(**kwargs):
        return [{"status": "submitted", "details": {"order_id": "order-1"}, "risk_approval_id": "risk-aapl"}]

    async def fake_audit_trade_decision(**kwargs):
        return {"ok": True}

    async def fake_trigger_learning_cycle_if_allowed(**kwargs):
        return {"applied": False, "pending": False, "reason": "empty_learning_delta"}

    monkeypatch.setattr("app.workflows.multi_analysis_workflow.fetch_context_value", fake_fetch_context_value)
    monkeypatch.setattr("app.workflows.multi_analysis_workflow.fetch_session_risk_contexts", fake_fetch_session_risk_contexts)
    monkeypatch.setattr("app.workflows.multi_analysis_workflow.analyze_single_asset", fake_analyze_single_asset)
    monkeypatch.setattr("app.workflows.multi_analysis_workflow.evaluate_portfolio_risk", fake_evaluate_portfolio_risk)
    monkeypatch.setattr("app.workflows.multi_analysis_workflow.execute_approved_trades", fake_execute_approved_trades)
    monkeypatch.setattr("app.workflows.multi_analysis_workflow.audit_trade_decision", fake_audit_trade_decision)
    monkeypatch.setattr("app.workflows.multi_analysis_workflow.trigger_learning_cycle_if_allowed", fake_trigger_learning_cycle_if_allowed)

    response = await run_multi_analysis_flow(MultiAgentRequestBody(tickers=["AAPL"]))

    assert response.data.execution_summary.total_trades_approved == 1
    assert response.data.execution_summary.total_trades_executed == 1
    assert response.data.execution_summary.total_trades_failed == 0
    assert response.data.results[0].execution.status == "submitted"
    assert response.data.results[0].execution.details == {"order_id": "order-1"}


@pytest.mark.asyncio
async def test_run_multi_analysis_flow_rejects_invalid_stock_scope(monkeypatch):
    def fake_validate_stock_scope(ticker):
        raise ValueError("invalid")

    monkeypatch.setattr("app.workflows.multi_analysis_workflow.validate_stock_scope", fake_validate_stock_scope)

    with pytest.raises(ValueError):
        await run_multi_analysis_flow(MultiAgentRequestBody(tickers=["BAD"]))

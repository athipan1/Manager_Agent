"""Single-symbol analysis route workflow for Manager_Agent.

This workflow composes the smaller service/workflow helpers that were extracted
from `app.main`: context loading, agent analysis, risk evaluation, execution,
audit, and learning. It is not wired into FastAPI routes yet.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Any, Dict, Optional

from fastapi import HTTPException

from .. import config
from ..config_manager import config_manager
from ..contracts import StandardAgentResponse
from ..database_client import DatabaseAgentClient
from ..execution_client import ExecutionAgentClient
from ..logger import report_logger
from ..models import AgentRequestBody, OrchestratorResponse
from ..resilient_client import AgentUnavailable
from ..stock_guard import StockGuardError, validate_stock_scope
from ..services.audit_service import audit_trade_decision, persist_signal
from ..services.context_service import fetch_context_value, fetch_session_risk_context
from ..services.performance_policy_review_service import run_performance_policy_review
from ..services.trade_plan_builder import attach_trade_plan_to_decision
from ..services.trade_plan_lifecycle_service import persist_trade_plan_created, persist_trade_plan_status
from .analysis_workflow import analyze_single_asset
from .execution_workflow import execute_trade
from .learning_workflow import trigger_learning_cycle_if_allowed
from .risk_workflow import evaluate_single_trade_risk, is_tradeable_verdict


def utc_now() -> datetime.datetime:
    """Return the current UTC timestamp."""
    return datetime.datetime.now(datetime.UTC)


def manager_metadata(
    *,
    risk_context_loaded: bool = False,
    learning_delta_applied: bool = False,
    learning_delta_pending: bool = False,
    learning_delta_skipped_reason: Optional[str] = None,
    dry_run: bool = False,
    policy_review: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build Manager response metadata, preserving the legacy response shape."""
    metadata = {
        "trading_mode": config.TRADING_MODE,
        "trading_enabled": config.TRADING_ENABLED,
        "allow_live_trading": config.ALLOW_LIVE_TRADING,
        "asset_class": config.ASSET_CLASS,
        "manual_approval_required": config.MANUAL_APPROVAL_REQUIRED,
        "risk_context_loaded": risk_context_loaded,
        "learning_delta_auto_apply_enabled": config.APPLY_LEARNING_DELTAS,
        "learning_delta_applied": learning_delta_applied,
        "learning_delta_pending": learning_delta_pending,
        "dry_run": dry_run,
        "policy_review_flow_enabled": config.POLICY_REVIEW_FLOW_ENABLED,
    }
    if learning_delta_skipped_reason:
        metadata["learning_delta_skipped_reason"] = learning_delta_skipped_reason
    if policy_review is not None:
        metadata["policy_review"] = policy_review
    return metadata


def _with_trade_plan_id(result: Dict[str, Any], trade_decision: Dict[str, Any]) -> Dict[str, Any]:
    trade_plan_id = trade_decision.get("trade_plan_id")
    if trade_plan_id:
        result["trade_plan_id"] = trade_plan_id
    return result


def execution_result_for_decision(
    *,
    trade_decision: Optional[Dict[str, Any]],
    dry_run: bool,
) -> Dict[str, Any]:
    """Return the non-submitting execution result for dry-run/rejected/no-decision cases."""
    if trade_decision is None:
        return {"status": "not_attempted", "reason": "No trade decision."}

    if dry_run:
        return _with_trade_plan_id(
            {
                "status": "dry_run",
                "reason": "Execution skipped by dry-run mode.",
                "risk_approval_id": trade_decision.get("risk_approval_id"),
            },
            trade_decision,
        )

    if not trade_decision.get("approved"):
        return _with_trade_plan_id(
            {
                "status": "rejected",
                "reason": trade_decision.get("reason"),
                "risk_approval_id": trade_decision.get("risk_approval_id"),
            },
            trade_decision,
        )

    if config.MANUAL_APPROVAL_REQUIRED:
        return _with_trade_plan_id(
            {
                "status": "manual_approval_required",
                "reason": "Manual approval is required before live stock execution.",
                "risk_approval_id": trade_decision.get("risk_approval_id"),
            },
            trade_decision,
        )

    return _with_trade_plan_id({"status": "ready_for_execution"}, trade_decision)


def lifecycle_status_for_execution_result(execution_result: Dict[str, Any]) -> tuple[str, str]:
    """Map Manager execution result states to Database TradePlan lifecycle states."""
    status = execution_result.get("status")
    if status == "submitted":
        return "execution_submitted", "TradePlan submitted to Execution_Agent."
    if status == "dry_run":
        return "queued", "Execution skipped by dry-run mode."
    if status == "manual_approval_required":
        return "queued", "Manual approval required before execution."
    if status == "rejected":
        return "rejected", str(execution_result.get("reason") or "Risk rejected TradePlan.")
    if status == "ready_for_execution":
        return "queued", "TradePlan ready for execution."
    return "queued", str(execution_result.get("reason") or f"Manager execution state: {status}")


async def run_single_analysis_flow(
    request: AgentRequestBody,
    *,
    dry_run: bool = False,
) -> StandardAgentResponse:
    """Run the complete Manager flow for one symbol.

    This is a route-ready replacement for the legacy `app.main._run_single_analysis_flow`.
    It remains unwired until a follow-up PR switches the FastAPI route to call it.
    """
    correlation_id = str(uuid.uuid4())
    ticker = request.ticker.upper()
    account_id = request.account_id if request.account_id is not None else config_manager.get("DEFAULT_ACCOUNT_ID")

    try:
        validate_stock_scope(ticker)
        async with DatabaseAgentClient() as db_client:
            balance = await db_client.get_account_balance(account_id, correlation_id)
            positions = await db_client.get_positions(account_id, correlation_id)
            context_value = await fetch_context_value(db_client, account_id, correlation_id)
            session_context = await fetch_session_risk_context(db_client, account_id, ticker, correlation_id)

            analysis_result = await analyze_single_asset(ticker, correlation_id)
            if "error" in analysis_result:
                raise HTTPException(status_code=500, detail=analysis_result["error"])

            final_verdict = analysis_result["final_verdict"]
            await persist_signal(db_client, account_id, analysis_result, correlation_id)

            trade_decision: Optional[Dict[str, Any]] = None
            execution_result: Dict[str, Any] = {"status": "not_attempted", "reason": "No trade decision."}

            if is_tradeable_verdict(final_verdict):
                trade_decision = evaluate_single_trade_risk(
                    ticker=ticker,
                    final_verdict=final_verdict,
                    analysis_result=analysis_result,
                    balance=balance,
                    positions=positions,
                    context_value=context_value,
                    session_context=session_context,
                    correlation_id=correlation_id,
                )
                attach_trade_plan_to_decision(
                    analysis_result=analysis_result,
                    trade_decision=trade_decision,
                    account_id=account_id,
                    correlation_id=correlation_id,
                    dry_run=dry_run,
                    source="single_analysis",
                )
                await persist_trade_plan_created(
                    db_client=db_client,
                    trade_decision=trade_decision,
                    correlation_id=correlation_id,
                )

                execution_result = execution_result_for_decision(
                    trade_decision=trade_decision,
                    dry_run=dry_run,
                )

                if execution_result.get("status") == "ready_for_execution":
                    async with ExecutionAgentClient() as exec_client:
                        execution_result = await execute_trade(
                            exec_client,
                            trade_decision,
                            account_id,
                            correlation_id,
                            db_client=db_client,
                        )
                        if trade_decision and trade_decision.get("trade_plan_id"):
                            execution_result["trade_plan_id"] = trade_decision.get("trade_plan_id")

                lifecycle_status, lifecycle_reason = lifecycle_status_for_execution_result(execution_result)
                await persist_trade_plan_status(
                    db_client=db_client,
                    trade_decision=trade_decision,
                    correlation_id=correlation_id,
                    status=lifecycle_status,
                    reason=lifecycle_reason,
                    execution_result=execution_result,
                )

            audit = await audit_trade_decision(
                db_client=db_client,
                account_id=account_id,
                correlation_id=correlation_id,
                flow="analyze",
                symbol=ticker,
                analysis_result=analysis_result,
                trade_decision=trade_decision,
                execution_result=execution_result,
                context_value=context_value,
                dry_run=dry_run,
            )

            report = OrchestratorResponse(
                report_id=correlation_id,
                ticker=ticker.upper(),
                timestamp=utc_now(),
                final_verdict=final_verdict,
                status=analysis_result["status"],
                details=analysis_result["details"],
            )

            learning_state = await trigger_learning_cycle_if_allowed(
                db_client=db_client,
                account_id=account_id,
                symbol=ticker,
                correlation_id=correlation_id,
                execution_result=execution_result,
                dry_run=dry_run,
            )

            policy_review = await run_performance_policy_review(
                db_client=db_client,
                account_id=account_id,
                symbol=ticker,
                initial_equity=float(balance.cash),
                correlation_id=correlation_id,
            )

            data = audit if dry_run else report
            return StandardAgentResponse(
                status="success",
                agent_type="manager-agent",
                version="1.0.0",
                timestamp=utc_now(),
                data=data,
                metadata=manager_metadata(
                    risk_context_loaded=True,
                    learning_delta_applied=learning_state["applied"],
                    learning_delta_pending=learning_state["pending"],
                    learning_delta_skipped_reason=learning_state["reason"],
                    dry_run=dry_run,
                    policy_review=policy_review,
                ),
            )
    except StockGuardError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AgentUnavailable as exc:
        report_logger.critical(f"An agent is unavailable: {exc}")
        raise HTTPException(status_code=503, detail=str(exc)) from exc

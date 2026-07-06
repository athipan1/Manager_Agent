"""Multi-asset analysis workflow for Manager_Agent.

This module is the route-ready orchestration layer for `/analyze-multi`. It
composes already extracted analysis, context, risk, execution, audit, and
learning helpers without wiring the route yet.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Union

from fastapi import HTTPException

from .. import config
from ..config_manager import config_manager
from ..contracts import StandardAgentResponse
from ..database_client import DatabaseAgentClient
from ..execution_client import ExecutionAgentClient
from ..logger import report_logger
from ..models import (
    AnalysisResult,
    AssetResult,
    ExecutionResult,
    ExecutionSummary,
    MultiAgentRequestBody,
    MultiOrchestratorResponse,
)
from ..resilient_client import AgentUnavailable
from ..services.audit_service import audit_trade_decision
from ..services.context_service import fetch_context_value, fetch_session_risk_contexts
from ..stock_guard import StockGuardError, validate_stock_scope
from .analysis_workflow import analyze_single_asset
from .execution_workflow import execute_trade
from .learning_workflow import most_impactful_approved_trade, trigger_learning_cycle_if_allowed
from .risk_workflow import approved_trades, evaluate_portfolio_risk
from .single_analysis_workflow import manager_metadata, utc_now


def execution_outcome_for_decision(
    decision: Dict[str, Any],
    execution_outcomes_by_symbol: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """Build the per-symbol execution result payload for a risk decision."""
    if decision.get("approved"):
        return execution_outcomes_by_symbol.get(
            decision["symbol"],
            {
                "status": "manual_approval_required" if config.MANUAL_APPROVAL_REQUIRED else "failed",
                "reason": (
                    "Manual approval is required before live stock execution."
                    if config.MANUAL_APPROVAL_REQUIRED
                    else "Approved trade was not executed."
                ),
                "risk_approval_id": decision.get("risk_approval_id"),
            },
        )

    return {
        "status": "rejected",
        "reason": decision.get("reason", "Reason not provided."),
        "details": None,
    }


async def execute_approved_trades(
    *,
    approved_decisions: List[Dict[str, Any]],
    account_id: Union[int, str],
    correlation_id: str,
    db_client: DatabaseAgentClient,
) -> List[Dict[str, Any]]:
    """Execute approved trades unless manual approval is required."""
    if not approved_decisions:
        return []

    if config.MANUAL_APPROVAL_REQUIRED:
        return [
            {
                "status": "manual_approval_required",
                "reason": "Manual approval is required before live stock execution.",
                "risk_approval_id": decision.get("risk_approval_id"),
            }
            for decision in approved_decisions
        ]

    async with ExecutionAgentClient() as exec_client:
        return await asyncio.gather(
            *[
                execute_trade(
                    exec_client,
                    decision,
                    account_id,
                    correlation_id,
                    db_client=db_client,
                )
                for decision in approved_decisions
            ]
        )


async def run_multi_analysis_flow(request: MultiAgentRequestBody) -> StandardAgentResponse:
    """Run the complete Manager flow for multiple symbols."""
    correlation_id = str(uuid.uuid4())
    account_id = request.account_id if request.account_id is not None else config_manager.get("DEFAULT_ACCOUNT_ID")

    try:
        tickers = [str(ticker).upper() for ticker in request.tickers]
        for ticker in tickers:
            validate_stock_scope(ticker)

        async with DatabaseAgentClient() as db_client:
            balance = await db_client.get_account_balance(account_id, correlation_id)
            positions = await db_client.get_positions(account_id, correlation_id)
            context_value = await fetch_context_value(db_client, account_id, correlation_id)
            session_context = await fetch_session_risk_contexts(db_client, account_id, tickers, correlation_id)
            cash_balance = Decimal(balance.cash_balance if balance else 0)

            analysis_results = await asyncio.gather(
                *[analyze_single_asset(ticker, correlation_id) for ticker in tickers]
            )
            valid_results = [result for result in analysis_results if "error" not in result]

            for result in valid_results:
                # Reuse audit service persistence behavior without duplicating signal logic here.
                await db_client.save_signal(
                    account_id=account_id,
                    symbol=result.get("ticker"),
                    correlation_id=correlation_id,
                    final_verdict=result.get("final_verdict"),
                    metadata={"analysis_status": result.get("status"), "batch": True},
                )

            trade_decisions = evaluate_portfolio_risk(
                analysis_results=valid_results,
                cash_balance=cash_balance,
                existing_positions=positions,
                context_value=context_value,
                session_context=session_context,
                correlation_id=correlation_id,
                account_id=account_id,
            )
            approved_decisions = approved_trades(trade_decisions)
            execution_outcomes = await execute_approved_trades(
                approved_decisions=approved_decisions,
                account_id=account_id,
                correlation_id=correlation_id,
                db_client=db_client,
            )

            execution_outcomes_by_symbol = {
                decision["symbol"]: outcome
                for decision, outcome in zip(approved_decisions, execution_outcomes)
            }
            decisions_by_symbol = {decision["symbol"]: decision for decision in trade_decisions}

            asset_responses: List[AssetResult] = []
            for result in valid_results:
                ticker = result["ticker"]
                decision = decisions_by_symbol.get(
                    ticker,
                    {
                        "approved": False,
                        "reason": "Not analyzed or verdict was hold.",
                        "symbol": ticker,
                    },
                )
                outcome = execution_outcome_for_decision(decision, execution_outcomes_by_symbol)
                exec_status = outcome.get("status", "failed")
                exec_details = outcome.get("details")
                exec_reason = outcome.get("reason") or decision.get("reason", "Reason not provided.")

                await audit_trade_decision(
                    db_client=db_client,
                    account_id=account_id,
                    correlation_id=correlation_id,
                    flow="analyze_multi",
                    symbol=ticker,
                    analysis_result=result,
                    trade_decision=decision,
                    execution_result={
                        "status": exec_status,
                        "reason": exec_reason,
                        "details": exec_details,
                    },
                    context_value=context_value,
                )

                asset_responses.append(
                    AssetResult(
                        analysis=AnalysisResult(
                            ticker=ticker,
                            final_verdict=result["final_verdict"],
                            status=result["status"],
                            details=result["details"],
                        ),
                        execution=ExecutionResult(
                            status=exec_status,
                            reason=exec_reason,
                            details=exec_details,
                        ),
                    )
                )

            total_executed = sum(1 for outcome in execution_outcomes if outcome.get("status") == "submitted")
            learning_state = {"applied": False, "pending": False, "reason": "no_approved_trade"}
            impactful_trade = most_impactful_approved_trade(approved_decisions)
            if impactful_trade and execution_outcomes:
                learning_state = await trigger_learning_cycle_if_allowed(
                    db_client=db_client,
                    account_id=account_id,
                    symbol=impactful_trade["symbol"],
                    correlation_id=correlation_id,
                    execution_result=execution_outcomes_by_symbol.get(impactful_trade["symbol"]),
                )

            multi_report = MultiOrchestratorResponse(
                multi_report_id=correlation_id,
                timestamp=utc_now(),
                execution_summary=ExecutionSummary(
                    total_trades_approved=len(approved_decisions),
                    total_trades_executed=total_executed,
                    total_trades_failed=len(execution_outcomes) - total_executed,
                ),
                results=asset_responses,
            )
            return StandardAgentResponse(
                status="success",
                agent_type="manager-agent",
                version="1.0.0",
                timestamp=utc_now(),
                data=multi_report,
                metadata=manager_metadata(
                    risk_context_loaded=True,
                    learning_delta_applied=learning_state["applied"],
                    learning_delta_pending=learning_state["pending"],
                    learning_delta_skipped_reason=learning_state["reason"],
                ),
            )
    except StockGuardError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AgentUnavailable as exc:
        report_logger.critical(f"An agent is unavailable: {exc}")
        raise HTTPException(status_code=503, detail=str(exc)) from exc

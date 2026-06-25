"""Discovery/analyze/trade workflow helpers for Manager_Agent.

This module prepares the route-ready workflow for `/discover-analyze-trade`
without wiring the route yet.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional, Union

from fastapi import HTTPException

from .. import config
from ..config_manager import config_manager
from ..contracts import StandardAgentResponse
from ..database_client import DatabaseAgentClient
from ..discover_report_builder import build_discover_allocation_report
from ..execution_client import ExecutionAgentClient
from ..logger import report_logger
from ..models import DiscoverAnalyzeTradeRequest
from ..resilient_client import AgentUnavailable
from ..scanner_client import ScannerAgentClient
from ..services.analysis_service import score_deep_analysis
from ..services.audit_service import audit_trade_decision, persist_signal
from ..services.context_service import fetch_context_value, fetch_session_risk_contexts
from ..services.exposure_service import total_position_exposure
from ..services.scanner_candidate_service import (
    scanner_candidate_metadata,
    scanner_candidate_score,
    scanner_candidate_symbol,
)
from ..stock_guard import StockGuardError, validate_stock_scope
from .analysis_workflow import analyze_single_asset
from .execution_workflow import execute_portfolio_batch, ensure_risk_approval_id
from .learning_workflow import most_impactful_approved_trade, trigger_learning_cycle_if_allowed
from .risk_workflow import approved_trades, evaluate_portfolio_risk
from .single_analysis_workflow import manager_metadata, utc_now


def scanner_payload(scan_response: Any) -> Dict[str, Any]:
    """Normalize Scanner_Agent response data into a dictionary payload."""
    scan_data = getattr(scan_response, "data", None)
    if hasattr(scan_data, "model_dump"):
        return scan_data.model_dump()
    if isinstance(scan_data, dict):
        return scan_data
    return {}


def select_unique_scanner_tickers(candidates: List[Any]) -> tuple[List[str], Dict[str, Any]]:
    """Return unique validated scanner symbols and a symbol->candidate mapping."""
    selected_tickers: List[str] = []
    ticker_to_scanner_candidate: Dict[str, Any] = {}

    for candidate in candidates:
        symbol = scanner_candidate_symbol(candidate)
        symbol = str(symbol).upper() if symbol else None
        if symbol and symbol not in ticker_to_scanner_candidate:
            validate_stock_scope(symbol)
            ticker_to_scanner_candidate[symbol] = candidate
            selected_tickers.append(symbol)

    return selected_tickers, ticker_to_scanner_candidate


def rank_discovery_candidates(
    *,
    valid_results: List[Dict[str, Any]],
    ticker_to_scanner_candidate: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Rank valid deep-analysis results with scanner candidate scores."""
    ranked: List[Dict[str, Any]] = []
    for result in valid_results:
        symbol = result["ticker"]
        scanner_candidate = ticker_to_scanner_candidate.get(symbol)
        score_breakdown = score_deep_analysis(result, scanner_candidate_score(scanner_candidate))
        ranked.append(
            {
                "symbol": symbol,
                "analysis": result,
                "scanner_candidate": scanner_candidate_metadata(scanner_candidate),
                "score_breakdown": score_breakdown,
            }
        )
    ranked.sort(key=lambda item: item["score_breakdown"]["final_opportunity_score"], reverse=True)
    return ranked


def no_scanner_candidates_response(
    *,
    correlation_id: str,
    scan_response: Any,
    scan_payload: Dict[str, Any],
) -> StandardAgentResponse:
    """Build the legacy-compatible no-candidates error response."""
    return StandardAgentResponse(
        status="error",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=utc_now(),
        data={
            "report_id": correlation_id,
            "stage": "scanner_discovery",
            "message": "Scanner returned zero candidates.",
            "scanner_error": getattr(scan_response, "error", None),
            "scanner_data": scan_payload,
        },
        metadata=manager_metadata(),
        error={"code": "NO_SCANNER_CANDIDATES", "message": "Scanner returned zero candidates."},
    )


def no_valid_analysis_response(
    *,
    correlation_id: str,
    selected_tickers: List[str],
    analysis_results: List[Dict[str, Any]],
) -> StandardAgentResponse:
    """Build the legacy-compatible no-valid-analysis error response."""
    return StandardAgentResponse(
        status="error",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=utc_now(),
        data={
            "report_id": correlation_id,
            "stage": "deep_analysis",
            "scanner_candidates": selected_tickers,
            "analysis_results": analysis_results,
        },
        metadata=manager_metadata(),
        error={"code": "NO_VALID_ANALYSIS", "message": "Technical/Fundamental agents returned no valid analysis."},
    )


def initial_discovery_execution_result(*, execute: bool) -> Dict[str, Any]:
    """Return initial execution result before portfolio risk/execution runs."""
    return {
        "status": "not_attempted",
        "reason": "request.execute=false" if not execute else "No selected positions passed portfolio selection.",
    }


async def run_discover_analyze_trade_flow(request: DiscoverAnalyzeTradeRequest) -> StandardAgentResponse:
    """Run Scanner discovery, deep analysis, allocation, risk, execution, and learning."""
    correlation_id = str(uuid.uuid4())
    account_id = request.account_id if request.account_id is not None else config_manager.get("DEFAULT_ACCOUNT_ID")

    try:
        async with ScannerAgentClient() as scanner_client:
            scan_response = await scanner_client.discover_best_fundamentals(
                correlation_id=correlation_id,
                max_universe=request.max_universe,
                top_n=request.top_n,
                exchange=request.exchange,
                max_workers=request.max_workers,
            )

        scan_payload = scanner_payload(scan_response)
        candidates = scan_payload.get("candidates", [])
        if not candidates:
            return no_scanner_candidates_response(
                correlation_id=correlation_id,
                scan_response=scan_response,
                scan_payload=scan_payload,
            )

        selected_tickers, ticker_to_scanner_candidate = select_unique_scanner_tickers(candidates)
        analysis_results = await asyncio.gather(
            *[analyze_single_asset(ticker, correlation_id) for ticker in selected_tickers]
        )
        valid_results = [result for result in analysis_results if "error" not in result]
        if not valid_results:
            return no_valid_analysis_response(
                correlation_id=correlation_id,
                selected_tickers=selected_tickers,
                analysis_results=analysis_results,
            )

        ranked = rank_discovery_candidates(
            valid_results=valid_results,
            ticker_to_scanner_candidate=ticker_to_scanner_candidate,
        )

        async with DatabaseAgentClient() as db_client:
            balance = await db_client.get_account_balance(account_id, correlation_id)
            positions = await db_client.get_positions(account_id, correlation_id)
            context_value = await fetch_context_value(db_client, account_id, correlation_id)
            portfolio_value = Decimal(balance.cash_balance if balance else 0) + total_position_exposure(positions)
            allocation_report = build_discover_allocation_report(
                ranked=ranked,
                portfolio_value=portfolio_value,
                min_final_score=request.min_final_score,
            )
            selected_positions = allocation_report.get("selected_positions") or []
            position_analysis_payloads = allocation_report.get("position_analysis_payloads") or []
            selected_symbols = [str(position.get("symbol") or "").upper() for position in selected_positions]
            session_context = await fetch_session_risk_contexts(
                db_client,
                account_id,
                selected_symbols,
                correlation_id,
            )

            for item in ranked:
                await persist_signal(
                    db_client,
                    account_id,
                    item["analysis"],
                    correlation_id,
                    extra_metadata={
                        "flow": "discover_analyze_trade",
                        "scanner_candidate": item["scanner_candidate"],
                        "score_breakdown": item["score_breakdown"],
                        "selected_for_portfolio": item["symbol"] in selected_symbols,
                    },
                )

            risk_approvals: List[Dict[str, Any]] = []
            execution_result: Dict[str, Any] = initial_discovery_execution_result(execute=request.execute)

            if request.execute and position_analysis_payloads:
                risk_approvals = evaluate_portfolio_risk(
                    analysis_results=position_analysis_payloads,
                    cash_balance=Decimal(balance.cash_balance if balance else 0),
                    existing_positions=positions,
                    context_value=context_value,
                    session_context=session_context,
                    correlation_id=correlation_id,
                )
                for decision in risk_approvals:
                    ensure_risk_approval_id(decision, correlation_id)

                approved_decisions = approved_trades(risk_approvals)
                if approved_decisions and config.MANUAL_APPROVAL_REQUIRED:
                    execution_result = {
                        "status": "manual_approval_required",
                        "reason": "Manual approval is required before live stock execution.",
                        "approved_positions": len(approved_decisions),
                        "risk_approval_ids": [decision.get("risk_approval_id") for decision in approved_decisions],
                    }
                elif approved_decisions:
                    async with ExecutionAgentClient() as exec_client:
                        execution_result = await execute_portfolio_batch(
                            exec_client=exec_client,
                            decisions=approved_decisions,
                            account_id=account_id,
                            correlation_id=correlation_id,
                            db_client=db_client,
                        )
                else:
                    execution_result = {
                        "status": "rejected",
                        "reason": "Risk rejected every selected portfolio position.",
                    }

                for payload in position_analysis_payloads:
                    symbol = payload.get("ticker")
                    decision = next(
                        (row for row in risk_approvals if row.get("symbol") == symbol),
                        {"approved": False, "symbol": symbol, "reason": "No risk decision generated."},
                    )
                    await audit_trade_decision(
                        db_client=db_client,
                        account_id=account_id,
                        correlation_id=correlation_id,
                        flow="discover_analyze_trade_portfolio",
                        symbol=symbol,
                        analysis_result=payload,
                        trade_decision=decision,
                        execution_result=execution_result,
                        context_value=context_value,
                    )

            approved_positions = [row for row in risk_approvals if row.get("approved")]
            learning_state = {"applied": False, "pending": False, "reason": "no_approved_trade"}
            impactful_trade = most_impactful_approved_trade(approved_positions)
            if impactful_trade:
                learning_state = await trigger_learning_cycle_if_allowed(
                    db_client=db_client,
                    account_id=account_id,
                    symbol=impactful_trade["symbol"],
                    correlation_id=correlation_id,
                    execution_result=execution_result,
                )

        data = {
            "report_id": correlation_id,
            "flow": "discover_analyze_trade",
            "mode": "portfolio_allocation",
            "scanner_metadata": scan_payload.get("metadata", {}),
            "scanner_count": len(candidates),
            "deep_analysis_count": len(valid_results),
            "top_10_symbols": selected_tickers,
            "allocation_plan": allocation_report.get("allocation_plan"),
            "bucket_selection": allocation_report.get("bucket_selection"),
            "selected_positions": selected_positions,
            "risk_approvals": risk_approvals,
            "execution_candidates": approved_positions,
            "execution": execution_result,
            "portfolio_summary": {
                "policy_name": (allocation_report.get("allocation_plan") or {}).get("policy_name"),
                "selected_positions": len(selected_positions),
                "approved_positions": len(approved_positions),
                "rejected_positions": len(risk_approvals) - len(approved_positions),
                "execution_status": execution_result.get("status"),
            },
            "ranked_candidates": allocation_report.get("ranked_candidates"),
            "legacy": {
                "winner": allocation_report.get("winner"),
                "trade_decision": approved_positions[0] if approved_positions else None,
                "risk_approval_id": approved_positions[0].get("risk_approval_id") if approved_positions else None,
            },
        }
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
            ),
        )
    except StockGuardError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AgentUnavailable as exc:
        report_logger.critical(f"An agent is unavailable: {exc}")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        report_logger.exception(f"Discover analyze trade failed: {exc}, correlation_id={correlation_id}")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

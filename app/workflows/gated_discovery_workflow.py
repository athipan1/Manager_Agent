"""Exposure-gated discovery/analyze/trade workflow.

This module keeps the existing discovery helpers but inserts the canonical
Exposure-Aware Trade Gate between allocation and downstream risk evaluation.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal
from typing import Any, Dict, List, Optional

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
from ..services.audit_service import audit_trade_decision, persist_signal
from ..services.backtest_execution_gate import (
    filter_candidates_with_backtest_gate,
)
from ..services.context_service import fetch_context_value, fetch_session_risk_contexts
from ..services.curator_observation_persistence import persist_curator_observations
from ..services.curator_signal_service import enrich_payloads_with_curator_signals
from ..services.exposure_aware_trade_gate import filter_candidates_with_exposure_gate
from ..services.exposure_service import total_position_exposure
from ..stock_guard import StockGuardError
from .analysis_workflow import analyze_single_asset
from .discovery_workflow import (
    initial_discovery_execution_result,
    no_scanner_candidates_response,
    no_valid_analysis_response,
    rank_discovery_candidates,
    scanner_payload,
    select_unique_scanner_tickers,
    skip_protected_portfolio_payloads,
)
from .execution_workflow import execute_portfolio_batch, ensure_risk_approval_id
from .learning_workflow import (
    most_impactful_approved_trade,
    trigger_learning_cycle_if_allowed,
)
from .risk_workflow import approved_trades, evaluate_portfolio_risk
from .single_analysis_workflow import manager_metadata, utc_now


def _symbol(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("ticker") or value.get("symbol") or "").upper()
    return str(
        getattr(value, "ticker", None)
        or getattr(value, "symbol", None)
        or ""
    ).upper()


def exposure_gate_blocked_execution(
    gate_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a stable execution result when no candidate survives the gate."""
    rejected = gate_result.get("rejected") or []
    return {
        "status": "blocked_by_exposure_gate",
        "reason": (
            "No candidate has verified remaining exposure capacity and "
            "operational safety."
        ),
        "rejected_candidates": rejected,
        "rejection_codes": sorted(
            {
                code
                for row in rejected
                for code in (row.get("rejection_codes") or [])
            }
        ),
    }


def backtest_gate_blocked_execution(
    gate_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a stable execution result when Backtest evidence is missing."""
    rejected = gate_result.get("rejected") or []
    return {
        "status": "blocked_by_backtest_gate",
        "reason": (
            "No exposure-approved candidate has an exact, fresh, passing "
            "Backtest result for its symbol, strategy, and timeframe."
        ),
        "rejected_candidates": rejected,
        "rejection_codes": sorted(
            {
                code
                for row in rejected
                for code in (row.get("rejection_codes") or [])
            }
        ),
    }


def gate_decision_by_symbol(
    gate_result: Dict[str, Any],
) -> Dict[str, Dict[str, Any]]:
    return {
        str(row.get("symbol") or "").upper(): row
        for row in gate_result.get("decisions") or []
        if row.get("symbol")
    }


async def run_gated_discover_analyze_trade_flow(
    request: DiscoverAnalyzeTradeRequest,
    *,
    database_sync_ok: bool = True,
    snapshot_age_seconds: Optional[float] = None,
    max_snapshot_age_seconds: float = 60.0,
) -> StandardAgentResponse:
    """Run discovery with exposure capacity and protection gates before Risk."""
    correlation_id = str(uuid.uuid4())
    account_id = (
        request.account_id
        if request.account_id is not None
        else config_manager.get("DEFAULT_ACCOUNT_ID")
    )

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

        selected_tickers, ticker_to_scanner_candidate = (
            select_unique_scanner_tickers(candidates)
        )
        analysis_results = await asyncio.gather(
            *[
                analyze_single_asset(ticker, correlation_id)
                for ticker in selected_tickers
            ]
        )
        valid_results = [
            result for result in analysis_results if "error" not in result
        ]
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
            balance = await db_client.get_account_balance(
                account_id,
                correlation_id,
            )
            positions = await db_client.get_positions(
                account_id,
                correlation_id,
            )
            orders = await db_client.get_orders(
                account_id,
                correlation_id,
            )
            context_value = await fetch_context_value(
                db_client,
                account_id,
                correlation_id,
            )
            cash_balance = Decimal(balance.cash_balance if balance else 0)
            portfolio_value = cash_balance + total_position_exposure(positions)

            allocation_report = build_discover_allocation_report(
                ranked=ranked,
                portfolio_value=portfolio_value,
                min_final_score=request.min_final_score,
                positions=positions,
            )
            pre_gate_selected_positions = (
                allocation_report.get("selected_positions") or []
            )
            pre_gate_payloads = (
                allocation_report.get("position_analysis_payloads") or []
            )

            exposure_gate = filter_candidates_with_exposure_gate(
                selected_positions=pre_gate_selected_positions,
                position_analysis_payloads=pre_gate_payloads,
                portfolio_value=portfolio_value,
                positions=positions,
                open_orders=orders,
                database_sync_ok=database_sync_ok,
                snapshot_age_seconds=snapshot_age_seconds,
                max_snapshot_age_seconds=max_snapshot_age_seconds,
            )
            selected_positions = exposure_gate["selected_positions"]
            position_analysis_payloads = exposure_gate[
                "position_analysis_payloads"
            ]
            gate_by_symbol = gate_decision_by_symbol(exposure_gate)

            pre_backtest_selected_positions = selected_positions
            pre_backtest_payloads = position_analysis_payloads
            backtest_execution_gate = (
                await filter_candidates_with_backtest_gate(
                    db_client=db_client,
                    selected_positions=pre_backtest_selected_positions,
                    position_analysis_payloads=pre_backtest_payloads,
                    correlation_id=correlation_id,
                    required=config.BACKTEST_EXECUTION_GATE_REQUIRED,
                    skill_id=config.BACKTEST_GATE_SKILL_ID,
                    strategy_id=config.BACKTEST_GATE_STRATEGY_ID,
                    timeframe=config.BACKTEST_GATE_TIMEFRAME,
                    max_age_hours=config.BACKTEST_GATE_MAX_AGE_HOURS,
                )
            )
            selected_positions = backtest_execution_gate[
                "selected_positions"
            ]
            position_analysis_payloads = backtest_execution_gate[
                "position_analysis_payloads"
            ]
            backtest_gate_by_symbol = {
                str(row.get("symbol") or "").upper(): row
                for row in backtest_execution_gate.get("decisions") or []
                if row.get("symbol")
            }

            (
                position_analysis_payloads,
                curator_signals,
            ) = await enrich_payloads_with_curator_signals(
                payloads=position_analysis_payloads,
                correlation_id=correlation_id,
            )
            curator_observation_persistence = await persist_curator_observations(
                db_client=db_client,
                account_id=account_id,
                correlation_id=correlation_id,
                curator_signals=curator_signals,
            )

            (
                risk_position_analysis_payloads,
                skipped_existing_protected_positions,
            ) = skip_protected_portfolio_payloads(
                selected_positions=selected_positions,
                position_analysis_payloads=position_analysis_payloads,
                positions=positions,
                orders=orders,
            )

            pre_gate_selected_symbols = {
                _symbol(position)
                for position in pre_gate_selected_positions
                if _symbol(position)
            }
            allowed_symbols = {
                _symbol(position)
                for position in selected_positions
                if _symbol(position)
            }
            skipped_protected_symbols = {
                str(row.get("symbol") or "").upper()
                for row in skipped_existing_protected_positions
            }
            risk_symbols = [
                _symbol(payload)
                for payload in risk_position_analysis_payloads
                if _symbol(payload)
            ]
            session_context = await fetch_session_risk_contexts(
                db_client,
                account_id,
                risk_symbols,
                correlation_id,
            )

            curator_signals_by_symbol = {
                str(signal.get("symbol") or "").upper(): signal
                for signal in curator_signals
                if isinstance(signal, dict)
            }

            for item in ranked:
                symbol = str(item.get("symbol") or "").upper()
                gate = gate_by_symbol.get(symbol)
                await persist_signal(
                    db_client,
                    account_id,
                    item["analysis"],
                    correlation_id,
                    extra_metadata={
                        "flow": "discover_analyze_trade",
                        "scanner_candidate": item["scanner_candidate"],
                        "score_breakdown": item["score_breakdown"],
                        "selected_before_exposure_gate": (
                            symbol in pre_gate_selected_symbols
                        ),
                        "selected_for_portfolio": symbol in allowed_symbols,
                        "exposure_gate_allowed": (
                            gate.get("allowed") if gate else None
                        ),
                        "exposure_gate_rejection_codes": (
                            gate.get("rejection_codes") if gate else []
                        ),
                        "backtest_gate_allowed": (
                            backtest_gate_by_symbol.get(symbol, {}).get(
                                "allowed"
                            )
                            if symbol in pre_gate_selected_symbols
                            else None
                        ),
                        "backtest_gate_rejection_codes": (
                            backtest_gate_by_symbol.get(symbol, {}).get(
                                "rejection_codes", []
                            )
                        ),
                        "skipped_existing_protected_position": (
                            symbol in skipped_protected_symbols
                        ),
                        "curator_signal": curator_signals_by_symbol.get(symbol),
                    },
                )

            risk_approvals: List[Dict[str, Any]] = []
            execution_result: Dict[str, Any] = (
                initial_discovery_execution_result(execute=request.execute)
            )

            if request.execute and pre_gate_payloads:
                if not pre_backtest_payloads:
                    execution_result = exposure_gate_blocked_execution(
                        exposure_gate
                    )
                elif not position_analysis_payloads:
                    execution_result = backtest_gate_blocked_execution(
                        backtest_execution_gate
                    )
                elif risk_position_analysis_payloads:
                    risk_approvals = evaluate_portfolio_risk(
                        analysis_results=risk_position_analysis_payloads,
                        cash_balance=cash_balance,
                        existing_positions=positions,
                        context_value=context_value,
                        session_context=session_context,
                        correlation_id=correlation_id,
                        account_id=account_id,
                    )
                    for decision in risk_approvals:
                        ensure_risk_approval_id(decision, correlation_id)

                    approved_decisions = approved_trades(risk_approvals)
                    if approved_decisions and config.MANUAL_APPROVAL_REQUIRED:
                        execution_result = {
                            "status": "manual_approval_required",
                            "reason": (
                                "Manual approval is required before live "
                                "stock execution."
                            ),
                            "approved_positions": len(approved_decisions),
                            "risk_approval_ids": [
                                decision.get("risk_approval_id")
                                for decision in approved_decisions
                            ],
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
                            "reason": (
                                "Risk rejected every exposure-gate-approved "
                                "portfolio position."
                            ),
                        }
                else:
                    execution_result = {
                        "status": "not_attempted",
                        "reason": (
                            "All exposure-gate-approved positions already "
                            "have protected open broker orders."
                        ),
                        "skipped_existing_protected_positions": (
                            skipped_existing_protected_positions
                        ),
                    }

                risk_by_symbol = {
                    str(row.get("symbol") or "").upper(): row
                    for row in risk_approvals
                    if row.get("symbol")
                }
                pre_gate_payload_by_symbol = {
                    _symbol(payload): payload
                    for payload in pre_gate_payloads
                    if _symbol(payload)
                }

                for symbol, payload in pre_gate_payload_by_symbol.items():
                    gate = gate_by_symbol.get(symbol) or {}
                    if not gate.get("allowed", False):
                        decision = {
                            "approved": False,
                            "symbol": symbol,
                            "status": "blocked_by_exposure_gate",
                            "reason": ",".join(
                                gate.get("rejection_codes") or []
                            ),
                            "exposure_gate": gate,
                        }
                    elif not backtest_gate_by_symbol.get(symbol, {}).get(
                        "allowed", False
                    ):
                        backtest_gate = backtest_gate_by_symbol.get(
                            symbol, {}
                        )
                        decision = {
                            "approved": False,
                            "symbol": symbol,
                            "status": "blocked_by_backtest_gate",
                            "reason": ",".join(
                                backtest_gate.get("rejection_codes") or []
                            ),
                            "exposure_gate": gate,
                            "backtest_gate": backtest_gate,
                        }
                    elif symbol in skipped_protected_symbols:
                        decision = {
                            "approved": False,
                            "symbol": symbol,
                            "status": "already_protected",
                            "reason": (
                                "Already protected with an open broker order."
                            ),
                            "exposure_gate": gate,
                        }
                    else:
                        decision = risk_by_symbol.get(
                            symbol,
                            {
                                "approved": False,
                                "symbol": symbol,
                                "reason": "No risk decision generated.",
                                "exposure_gate": gate,
                            },
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

            approved_positions = [
                row for row in risk_approvals if row.get("approved")
            ]
            learning_state = {
                "applied": False,
                "pending": False,
                "reason": "no_approved_trade",
            }
            impactful_trade = most_impactful_approved_trade(
                approved_positions
            )
            if impactful_trade:
                learning_state = await trigger_learning_cycle_if_allowed(
                    db_client=db_client,
                    account_id=account_id,
                    symbol=impactful_trade["symbol"],
                    correlation_id=correlation_id,
                    execution_result=execution_result,
                )

        cumulative_readiness = curator_observation_persistence.get("readiness")
        readiness_eligible = (
            cumulative_readiness.get("required_mode_eligible")
            if isinstance(cumulative_readiness, dict)
            else False
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
            "pre_gate_selected_positions": pre_gate_selected_positions,
            "pre_backtest_selected_positions": (
                pre_backtest_selected_positions
            ),
            "selected_positions": selected_positions,
            "exposure_gate": exposure_gate,
            "backtest_execution_gate": backtest_execution_gate,
            "skipped_existing_protected_positions": (
                skipped_existing_protected_positions
            ),
            "curator_signals": curator_signals,
            "curator_observation_persistence": curator_observation_persistence,
            "curator_observation_readiness": cumulative_readiness,
            "risk_approvals": risk_approvals,
            "execution_candidates": approved_positions,
            "execution": execution_result,
            "portfolio_summary": {
                "policy_name": (
                    allocation_report.get("allocation_plan") or {}
                ).get("policy_name"),
                "selected_before_exposure_gate": len(
                    pre_gate_selected_positions
                ),
                "selected_positions": len(selected_positions),
                "exposure_gate_rejected_positions": len(
                    exposure_gate.get("rejected") or []
                ),
                "exposure_gate_global_new_entry_blocked": (
                    exposure_gate.get("summary") or {}
                ).get("global_new_entry_blocked", False),
                "selected_before_backtest_gate": len(
                    pre_backtest_selected_positions
                ),
                "backtest_gate_required": (
                    backtest_execution_gate.get("required", False)
                ),
                "backtest_gate_allowed_positions": (
                    backtest_execution_gate.get("summary") or {}
                ).get("allowed_count", 0),
                "backtest_gate_rejected_positions": (
                    backtest_execution_gate.get("summary") or {}
                ).get("rejected_count", 0),
                "approved_positions": len(approved_positions),
                "rejected_positions": (
                    len(risk_approvals) - len(approved_positions)
                ),
                "skipped_existing_protected_positions": len(
                    skipped_existing_protected_positions
                ),
                "curator_signals": len(curator_signals),
                "curator_observation_persistence_status": (
                    curator_observation_persistence.get("status")
                ),
                "curator_observations_persisted": (
                    curator_observation_persistence.get("persisted_count", 0)
                ),
                "curator_required_mode_cumulative_eligible": readiness_eligible,
                "execution_status": execution_result.get("status"),
            },
            "ranked_candidates": allocation_report.get("ranked_candidates"),
            "legacy": {
                "winner": allocation_report.get("winner"),
                "trade_decision": (
                    approved_positions[0] if approved_positions else None
                ),
                "risk_approval_id": (
                    approved_positions[0].get("risk_approval_id")
                    if approved_positions
                    else None
                ),
            },
        }
        return StandardAgentResponse(
            status="success",
            agent_type="manager-agent",
            version="1.0.0",
            timestamp=utc_now(),
            data=data,
            metadata={
                **manager_metadata(
                    risk_context_loaded=True,
                    learning_delta_applied=learning_state["applied"],
                    learning_delta_pending=learning_state["pending"],
                    learning_delta_skipped_reason=learning_state["reason"],
                ),
                "exposure_gate_allowed_count": (
                    exposure_gate.get("summary") or {}
                ).get("allowed_count", 0),
                "exposure_gate_rejected_count": (
                    exposure_gate.get("summary") or {}
                ).get("rejected_count", 0),
                "backtest_gate_required": (
                    backtest_execution_gate.get("required", False)
                ),
                "backtest_gate_allowed_count": (
                    backtest_execution_gate.get("summary") or {}
                ).get("allowed_count", 0),
                "backtest_gate_rejected_count": (
                    backtest_execution_gate.get("summary") or {}
                ).get("rejected_count", 0),
            },
        )

    except StockGuardError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AgentUnavailable as exc:
        report_logger.critical(f"An agent is unavailable: {exc}")
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        report_logger.exception(
            "Gated discover analyze trade failed: "
            f"{exc}, correlation_id={correlation_id}"
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc

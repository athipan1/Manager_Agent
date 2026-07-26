"""Read-only Scanner preselection for the hourly Backtest pipeline.

This workflow intentionally consumes the broker snapshot that the host coordinator
already reconciled and verified before Scanner starts. It never calls
Execution_Agent, Risk_Agent, Performance_Agent, or order-entry code. The later
hourly trade phase performs the normal required reconciliation again before any
execution decision.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException

from ..config_manager import config_manager
from ..contracts import StandardAgentResponse
from ..discover_report_builder import build_discover_allocation_report
from ..logger import report_logger
from ..models import DiscoverAnalyzeTradeRequest
from ..resilient_client import AgentUnavailable
from ..scanner_client import ScannerAgentClient
from ..services.database_sync_gate import (
    database_sync_allows_automation,
    database_sync_block_reason,
    database_sync_summary,
)
from ..services.exposure_aware_trade_gate import filter_candidates_with_exposure_gate
from ..services.exposure_service import total_position_exposure
from ..stock_guard import StockGuardError
from .analysis_workflow import analyze_single_asset
from .discovery_workflow import (
    no_scanner_candidates_response,
    no_valid_analysis_response,
    rank_discovery_candidates,
    scanner_payload,
    select_unique_scanner_tickers,
)
from .guarded_discovery_workflow import load_database_sync_status
from .single_analysis_workflow import manager_metadata, utc_now


def _verified_database_context(
    database_sync: dict[str, Any],
) -> tuple[Decimal, list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract canonical portfolio context from one verified sync-status payload.

    Database_Agent's `/broker-sync/status` response already contains the account,
    positions, and open orders used to prove Database/Alpaca parity. Reusing that
    same payload keeps preselection internally consistent and avoids a second
    remote Database_Agent request after the expensive Scanner pass.
    """

    database = database_sync.get("database")
    if not isinstance(database, dict):
        raise AgentUnavailable(
            "Verified Database/Alpaca status omitted canonical database context."
        )

    account = database.get("account")
    positions = database.get("positions")
    open_orders = database.get("open_orders")
    if not isinstance(account, dict):
        raise AgentUnavailable(
            "Verified Database/Alpaca status omitted canonical account context."
        )
    if not isinstance(positions, list) or not all(
        isinstance(row, dict) for row in positions
    ):
        raise AgentUnavailable(
            "Verified Database/Alpaca status returned invalid position context."
        )
    if not isinstance(open_orders, list) or not all(
        isinstance(row, dict) for row in open_orders
    ):
        raise AgentUnavailable(
            "Verified Database/Alpaca status returned invalid open-order context."
        )

    raw_cash = account.get("cash_balance")
    if raw_cash in (None, ""):
        raise AgentUnavailable(
            "Verified Database/Alpaca status omitted the canonical cash balance."
        )
    try:
        cash_balance = Decimal(str(raw_cash))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise AgentUnavailable(
            "Verified Database/Alpaca status returned an invalid cash balance."
        ) from exc
    if not cash_balance.is_finite():
        raise AgentUnavailable(
            "Verified Database/Alpaca status returned a non-finite cash balance."
        )

    return (
        cash_balance,
        [dict(row) for row in positions],
        [dict(row) for row in open_orders],
    )


async def run_scanner_preselection_flow(
    request: DiscoverAnalyzeTradeRequest,
) -> StandardAgentResponse:
    """Discover and exposure-filter candidates without execution-side services."""

    if request.execute:
        raise HTTPException(
            status_code=400,
            detail="Scanner preselection requires execute=false.",
        )

    correlation_id = request.portfolio_cycle_id or str(uuid.uuid4())
    account_id = (
        request.account_id
        if request.account_id is not None
        else config_manager.get("DEFAULT_ACCOUNT_ID")
    )

    try:
        database_sync = await load_database_sync_status(account_id, correlation_id)
        if not database_sync_allows_automation(database_sync):
            raise AgentUnavailable(
                "Scanner preselection requires a verified Database/Alpaca snapshot: "
                + database_sync_block_reason(database_sync)
            )

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
            response = no_scanner_candidates_response(
                correlation_id=correlation_id,
                scan_response=scan_response,
                scan_payload=scan_payload,
            )
            if isinstance(response.data, dict):
                response.data["preselection_only"] = True
                response.data["database_sync"] = database_sync
            return response

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
            response = no_valid_analysis_response(
                correlation_id=correlation_id,
                selected_tickers=selected_tickers,
                analysis_results=analysis_results,
            )
            if isinstance(response.data, dict):
                response.data["preselection_only"] = True
                response.data["database_sync"] = database_sync
            return response

        ranked = rank_discovery_candidates(
            valid_results=valid_results,
            ticker_to_scanner_candidate=ticker_to_scanner_candidate,
        )

        cash_balance, positions, orders = _verified_database_context(database_sync)
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
            database_sync_ok=True,
            snapshot_age_seconds=None,
            max_snapshot_age_seconds=60.0,
        )
        selected_positions = exposure_gate["selected_positions"]

        data = {
            "report_id": correlation_id,
            "flow": "scanner_preselection",
            "mode": "read_only_pre_backtest",
            "preselection_only": True,
            "scanner_metadata": scan_payload.get("metadata", {}),
            "scanner_count": len(candidates),
            "deep_analysis_count": len(valid_results),
            "top_10_symbols": selected_tickers,
            "allocation_plan": allocation_report.get("allocation_plan"),
            "bucket_selection": allocation_report.get("bucket_selection"),
            "pre_gate_selected_positions": pre_gate_selected_positions,
            "pre_backtest_selected_positions": selected_positions,
            "selected_positions": selected_positions,
            "exposure_gate": exposure_gate,
            "backtest_execution_gate": {
                "required": False,
                "status": "skipped",
                "reason": "exact Backtest runs after this preselection response",
            },
            "risk_approvals": [],
            "execution_candidates": [],
            "execution": {
                "status": "not_requested",
                "reason": "read-only Scanner preselection",
            },
            "database_sync": database_sync,
            "database_context": {
                "source": "broker_sync_status.database",
                "position_count": len(positions),
                "open_order_count": len(orders),
            },
            "broker_snapshot_capture": {
                "status": "skipped",
                "reason": "verified Database_Agent sync-status payload reused",
            },
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
                "database_sync_status": database_sync_summary(
                    database_sync
                ).get("status"),
                "database_context_source": "broker_sync_status.database",
                "execution_status": "not_requested",
            },
            "ranked_candidates": allocation_report.get("ranked_candidates"),
            "legacy": {
                "winner": allocation_report.get("winner"),
                "trade_decision": None,
                "risk_approval_id": None,
            },
        }
        return StandardAgentResponse(
            status="success",
            agent_type="manager-agent",
            version="1.0.0",
            timestamp=utc_now(),
            correlation_id=correlation_id,
            data=data,
            metadata={
                **manager_metadata(
                    risk_context_loaded=False,
                    learning_delta_applied=False,
                    learning_delta_pending=False,
                    learning_delta_skipped_reason="scanner_preselection_only",
                ),
                "preselection_only": True,
                "execution_agent_required": False,
                "database_context_source": "broker_sync_status.database",
                "database_context_request_count": 1,
                "exposure_gate_allowed_count": (
                    exposure_gate.get("summary") or {}
                ).get("allowed_count", 0),
                "exposure_gate_rejected_count": (
                    exposure_gate.get("summary") or {}
                ).get("rejected_count", 0),
            },
        )
    except StockGuardError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except AgentUnavailable as exc:
        report_logger.critical(
            "Scanner preselection dependency unavailable: "
            f"{exc}, correlation_id={correlation_id}"
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        report_logger.exception(
            "Scanner preselection failed: "
            f"{exc}, correlation_id={correlation_id}"
        )
        raise HTTPException(status_code=500, detail=str(exc)) from exc

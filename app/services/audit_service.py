"""Audit and signal persistence helpers for Manager_Agent.

This module centralizes Manager audit report creation and signal persistence.
It does not submit orders or call broker/execution services.
"""

from __future__ import annotations

import datetime
from decimal import Decimal
from typing import Any, Dict, Optional, Union

from .. import config
from ..database_client import DatabaseAgentClient
from ..logger import report_logger
from .order_builder import strategy_bucket_from_decision
from .serialization_service import jsonable

UNKNOWN_STRATEGY_BUCKET = "unassigned"


def utc_now() -> datetime.datetime:
    """Return the current UTC timestamp."""
    return datetime.datetime.now(datetime.UTC)


def _strategy_bucket_from_audit_inputs(
    analysis_result: Optional[Dict[str, Any]],
    trade_decision: Optional[Dict[str, Any]],
) -> str:
    if trade_decision:
        bucket = strategy_bucket_from_decision(trade_decision)
        if bucket != UNKNOWN_STRATEGY_BUCKET:
            return bucket
    analysis_result = analysis_result or {}
    portfolio_context = analysis_result.get("portfolio_context") or {}
    metadata = analysis_result.get("metadata") or {}
    return str(
        analysis_result.get("strategy_bucket")
        or portfolio_context.get("strategy_bucket")
        or portfolio_context.get("bucket")
        or metadata.get("strategy_bucket")
        or metadata.get("bucket")
        or UNKNOWN_STRATEGY_BUCKET
    )


def _trade_plan_snapshot(trade_decision: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not trade_decision:
        return None
    trade_plan = trade_decision.get("trade_plan")
    return trade_plan if isinstance(trade_plan, dict) else None


def dry_run_report(
    *,
    correlation_id: str,
    flow: str,
    symbol: Optional[str],
    analysis_result: Optional[Dict[str, Any]],
    trade_decision: Optional[Dict[str, Any]],
    execution_result: Optional[Dict[str, Any]],
    context_value: Decimal,
    dry_run: bool,
    generated_at: Optional[datetime.datetime] = None,
) -> Dict[str, Any]:
    """Build a JSON-friendly dry-run/audit report.

    The shape mirrors the legacy `app.main._dry_run_report` payload so it can
    be wired into existing endpoints without changing API responses.
    """
    timestamp = generated_at or utc_now()
    strategy_bucket = _strategy_bucket_from_audit_inputs(analysis_result, trade_decision)
    trade_plan = _trade_plan_snapshot(trade_decision)
    report = {
        "report_id": correlation_id,
        "flow": flow,
        "symbol": symbol,
        "dry_run": dry_run,
        "trading_mode": config.TRADING_MODE,
        "trading_enabled": config.TRADING_ENABLED,
        "risk_context": {
            "open_orders_exposure": jsonable(context_value),
            "session": jsonable((trade_decision or {}).get("session_risk_context")),
            "loaded": True,
        },
        "analysis": jsonable(analysis_result),
        "trade_decision": jsonable(trade_decision),
        "trade_plan": jsonable(trade_plan),
        "risk_approval_id": trade_decision.get("risk_approval_id") if trade_decision else None,
        "trade_plan_id": trade_decision.get("trade_plan_id") if trade_decision else None,
        "execution": jsonable(execution_result),
        "generated_at": timestamp.isoformat(),
    }
    if strategy_bucket != UNKNOWN_STRATEGY_BUCKET:
        report["strategy_bucket"] = strategy_bucket
    return report


async def audit_trade_decision(
    *,
    db_client: Optional[DatabaseAgentClient],
    account_id: Union[int, str],
    correlation_id: str,
    flow: str,
    symbol: str,
    analysis_result: Optional[Dict[str, Any]],
    trade_decision: Optional[Dict[str, Any]],
    execution_result: Optional[Dict[str, Any]],
    context_value: Decimal,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Build and optionally persist a trade decision audit report."""
    audit = dry_run_report(
        correlation_id=correlation_id,
        flow=flow,
        symbol=symbol,
        analysis_result=analysis_result,
        trade_decision=trade_decision,
        execution_result=execution_result,
        context_value=context_value,
        dry_run=dry_run,
    )
    strategy_bucket = _strategy_bucket_from_audit_inputs(analysis_result, trade_decision)
    trade_plan = _trade_plan_snapshot(trade_decision)
    report_logger.info(f"trade_decision_audit={jsonable(audit)}")

    if db_client is not None:
        try:
            metadata = {
                "audit": jsonable(audit),
                "risk_approval_id": audit.get("risk_approval_id"),
                "trade_plan_id": audit.get("trade_plan_id"),
                "trade_plan": jsonable(trade_plan),
                "dry_run": dry_run,
                "flow": flow,
            }
            if strategy_bucket != UNKNOWN_STRATEGY_BUCKET:
                metadata["strategy_bucket"] = strategy_bucket
            await db_client.save_signal(
                account_id=account_id,
                symbol=symbol,
                correlation_id=correlation_id,
                final_verdict=(analysis_result or {}).get("final_verdict"),
                metadata=metadata,
            )
        except Exception as exc:
            report_logger.warning(
                f"Failed to persist trade decision audit for {symbol}: {exc}, "
                f"correlation_id={correlation_id}"
            )
    return audit


async def persist_signal(
    db_client: DatabaseAgentClient,
    account_id: Union[int, str],
    analysis_result: Dict[str, Any],
    correlation_id: str,
    extra_metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Persist a manager analysis signal to Database_Agent.

    Persistence failures are logged but not raised, preserving the legacy
    Manager behavior.
    """
    try:
        details = analysis_result.get("details")
        tech_detail = details.technical if details else None
        fund_detail = details.fundamental if details else None
        metadata = extra_metadata or {}
        strategy_bucket = _strategy_bucket_from_audit_inputs(analysis_result, metadata)
        signal_metadata = {
            "analysis_status": analysis_result.get("status"),
            "technical_action": tech_detail.action if tech_detail else None,
            "fundamental_action": fund_detail.action if fund_detail else None,
            **metadata,
        }
        if strategy_bucket != UNKNOWN_STRATEGY_BUCKET:
            signal_metadata["strategy_bucket"] = strategy_bucket
        await db_client.save_signal(
            account_id=account_id,
            symbol=analysis_result.get("ticker"),
            correlation_id=correlation_id,
            technical_score=tech_detail.score if tech_detail else None,
            fundamental_score=fund_detail.score if fund_detail else None,
            final_verdict=analysis_result.get("final_verdict"),
            metadata=signal_metadata,
        )
    except Exception as exc:
        report_logger.warning(
            f"Failed to persist signal for {analysis_result.get('ticker')}: {exc}, "
            f"correlation_id={correlation_id}"
        )

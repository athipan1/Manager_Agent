"""Trade replay routes for Manager_Agent."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any, Dict

from fastapi import APIRouter

from ..contracts import StandardAgentResponse
from ..logger import report_logger
from ..services.audit_service import dry_run_report
from ..services.serialization_service import as_decimal, jsonable
from ..workflows.single_analysis_workflow import manager_metadata, utc_now

router = APIRouter()


@router.post("/trade-replay", response_model=StandardAgentResponse)
async def trade_replay(payload: Dict[str, Any]):
    """Replay a trade decision payload as a dry-run audit report."""
    correlation_id = str(uuid.uuid4())
    context_value: Decimal = as_decimal((payload.get("risk_context") or {}).get("open_orders_exposure", 0))
    audit = dry_run_report(
        correlation_id=correlation_id,
        flow="trade_replay",
        symbol=payload.get("symbol"),
        analysis_result=payload.get("analysis"),
        trade_decision=payload.get("trade_decision"),
        execution_result=payload.get("execution"),
        context_value=context_value,
        dry_run=True,
    )
    report_logger.info(f"trade_replay_report={jsonable(audit)}")
    return StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=utc_now(),
        data=audit,
        metadata=manager_metadata(risk_context_loaded=True, dry_run=True),
    )

from typing import Optional

from fastapi import APIRouter, Query

from .alerts import alert_service
from .contracts import StandardAgentResponse
from .models import QueueStatusAlertRequest, ReconciliationAlertRequest

router = APIRouter(prefix="/alerts", tags=["Operational Alerts"])


@router.get("", response_model=StandardAgentResponse[dict])
async def list_alerts(limit: int = Query(100, ge=1, le=500), alert_type: Optional[str] = None):
    return StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        data={"events": alert_service.list_events(limit=limit, alert_type=alert_type)},
    )


@router.get("/summary", response_model=StandardAgentResponse[dict])
async def alert_summary():
    return StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        data=alert_service.summary(),
    )


@router.post("/queue-status", response_model=StandardAgentResponse[dict])
async def queue_status_alert(payload: QueueStatusAlertRequest):
    event = alert_service.record_queue_status(
        queue_name=payload.queue_name,
        oldest_age_seconds=payload.oldest_age_seconds,
        pending_count=payload.pending_count,
        correlation_id=payload.correlation_id,
        metadata=payload.metadata,
    )
    return StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        data={"alert_emitted": event is not None, "event": event},
    )


@router.post("/reconciliation", response_model=StandardAgentResponse[dict])
async def reconciliation_alert(payload: ReconciliationAlertRequest):
    event = alert_service.record_reconciliation_result(
        correlation_id=payload.correlation_id,
        mismatch_count=payload.mismatch_count,
        metadata=payload.metadata,
    )
    return StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        data={"alert_emitted": event is not None, "event": event},
    )

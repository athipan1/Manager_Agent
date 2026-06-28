"""Best-effort TradePlan lifecycle persistence helpers.

These helpers keep Database_Agent as the lifecycle ledger for TradePlan records
without making Manager_Agent's trading flow dependent on Database write success.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel

from ..contracts import TradePlan
from ..logger import report_logger
from .serialization_service import jsonable

TRADE_PLANS_ENDPOINT = "/trade-plans"


def _coerce_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return {}


def _trade_plan_snapshot(trade_decision: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(trade_decision, dict):
        return None
    trade_plan = trade_decision.get("trade_plan")
    return trade_plan if isinstance(trade_plan, dict) else None


def trade_plan_create_payload(trade_plan: Dict[str, Any]) -> Dict[str, Any]:
    plan = TradePlan.model_validate(trade_plan)
    status = plan.status.value if hasattr(plan.status, "value") else str(plan.status)
    lifecycle_status = "created"
    if status == "risk_approved":
        lifecycle_status = "risk_approved"
    elif status == "risk_pending":
        lifecycle_status = "risk_pending"
    elif status == "rejected":
        lifecycle_status = "rejected"

    return {
        "trade_plan_id": plan.plan_id,
        "account_id": plan.account_id,
        "symbol": plan.symbol,
        "side": plan.side.value if hasattr(plan.side, "value") else str(plan.side),
        "status": lifecycle_status,
        "correlation_id": plan.correlation_id,
        "source": "manager-agent",
        "strategy": plan.strategy,
        "strategy_bucket": plan.strategy_bucket,
        "risk_approval_id": plan.risk_approval_id,
        "plan": plan.model_dump(mode="json"),
        "metadata": {
            "manager_trade_plan_status": status,
            "dry_run": plan.dry_run,
            "approved": bool(plan.metadata.get("approved")) if isinstance(plan.metadata, dict) else False,
        },
    }


def trade_plan_status_payload(
    *,
    status: str,
    reason: Optional[str] = None,
    trade_decision: Optional[Dict[str, Any]] = None,
    execution_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    execution_result = execution_result or {}
    payload = {
        "status": status,
        "reason": reason,
        "metadata": {
            "execution_result": jsonable(execution_result),
        },
    }
    risk_approval_id = (trade_decision or {}).get("risk_approval_id") or execution_result.get("risk_approval_id")
    if risk_approval_id:
        payload["risk_approval_id"] = str(risk_approval_id)
    order = execution_result.get("order") if isinstance(execution_result, dict) else None
    if isinstance(order, dict) and order.get("order_id") is not None:
        payload["order_id"] = order.get("order_id")
    job = execution_result.get("execution_job") if isinstance(execution_result, dict) else None
    if isinstance(job, dict) and job.get("job_id") is not None:
        payload["execution_job_id"] = str(job.get("job_id"))
    broker_order_id = execution_result.get("broker_order_id")
    if not broker_order_id and isinstance(order, dict):
        broker_order_id = order.get("broker_order_id")
    if broker_order_id:
        payload["broker_order_id"] = str(broker_order_id)
    return payload


async def persist_trade_plan_created(
    *,
    db_client: Any,
    trade_decision: Optional[Dict[str, Any]],
    correlation_id: str,
) -> Optional[Dict[str, Any]]:
    trade_plan = _trade_plan_snapshot(trade_decision)
    if not trade_plan:
        return None
    try:
        payload = trade_plan_create_payload(trade_plan)
        response = await db_client._post(TRADE_PLANS_ENDPOINT, correlation_id, json_data=payload)
        data = _coerce_dict(db_client.validate_standard_response(response).data)
        if isinstance(trade_decision, dict):
            trade_decision["trade_plan_persisted"] = True
        return data
    except Exception as exc:
        if isinstance(trade_decision, dict):
            trade_decision["trade_plan_persist_error"] = str(exc)
        report_logger.warning(
            f"Failed to persist TradePlan create event: {exc}, correlation_id={correlation_id}"
        )
        return None


async def persist_trade_plan_status(
    *,
    db_client: Any,
    trade_decision: Optional[Dict[str, Any]],
    correlation_id: str,
    status: str,
    reason: Optional[str] = None,
    execution_result: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    trade_plan = _trade_plan_snapshot(trade_decision)
    if not trade_plan or not trade_plan.get("plan_id"):
        return None
    try:
        payload = trade_plan_status_payload(
            status=status,
            reason=reason,
            trade_decision=trade_decision,
            execution_result=execution_result,
        )
        endpoint = f"{TRADE_PLANS_ENDPOINT}/{trade_plan['plan_id']}/status"
        response = await db_client._post(endpoint, correlation_id, json_data=payload)
        data = _coerce_dict(db_client.validate_standard_response(response).data)
        if isinstance(trade_decision, dict):
            trade_decision["trade_plan_last_persisted_status"] = status
        return data
    except Exception as exc:
        if isinstance(trade_decision, dict):
            trade_decision["trade_plan_persist_error"] = str(exc)
        report_logger.warning(
            f"Failed to persist TradePlan status {status}: {exc}, correlation_id={correlation_id}"
        )
        return None

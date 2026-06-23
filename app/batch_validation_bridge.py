from __future__ import annotations

import uuid
from typing import Any, Dict, List, Union

from .contracts import CreateOrderRequest, OrderSide, OrderType


BUCKET_ORDER = ("core_dividend", "value_rebound", "news_momentum")


def _qty(row: Dict[str, Any]) -> int:
    for key in ("position_size", "final_quantity", "quantity"):
        try:
            value = int(row.get(key) or 0)
            if value > 0:
                return value
        except Exception:
            pass
    return 0


def _side(value: Any) -> OrderSide:
    return OrderSide.SELL if "sell" in str(value or "").lower() else OrderSide.BUY


def build_batch_validation_requests(bucket_risk_decisions: Dict[str, Any], account_id: Union[int, str]) -> List[CreateOrderRequest]:
    requests: List[CreateOrderRequest] = []
    for bucket in BUCKET_ORDER:
        for row in bucket_risk_decisions.get(bucket, []) or []:
            if not row.get("approved"):
                continue
            qty = _qty(row)
            symbol = row.get("symbol")
            approval = row.get("risk_approval_id") or row.get("approval_id")
            if not symbol or qty <= 0 or not approval:
                continue
            requests.append(CreateOrderRequest(
                client_order_id=row.get("client_order_id") or str(uuid.uuid4()),
                account_id=account_id,
                symbol=str(symbol).upper(),
                side=_side(row.get("action")),
                order_type=OrderType.MARKET,
                price=row.get("entry_price"),
                quantity=qty,
                final_quantity=qty,
                strategy_bucket=row.get("strategy_bucket") or bucket,
                risk_approval_id=str(approval),
                guard_plan=row.get("guard_plan") or {"source": "batch_validation"},
                protective_exit=row.get("protective_exit"),
            ))
    return requests


async def validate_bucket_batch(*, execution_client, bucket_risk_decisions: Dict[str, Any], account_id: Union[int, str], correlation_id: str) -> Dict[str, Any]:
    requests = build_batch_validation_requests(bucket_risk_decisions, account_id)
    if not requests:
        return {"approved": False, "reason": "no_valid_requests", "requests": []}
    response = await execution_client.validate_order_batch(requests, correlation_id)
    data = response.data or {}
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    return {
        "approved": bool((data or {}).get("approved")),
        "requests": [request.model_dump(mode="json") for request in requests],
        "execution_validation": data,
    }


async def maybe_execute_validated_batch(
    *,
    execution_client,
    validation_result: Dict[str, Any],
    enabled: bool,
    manual_approval_required: bool,
    correlation_id: str,
) -> Dict[str, Any]:
    """Run the guarded batch endpoint only after validation and explicit opt-in."""
    requests_data = validation_result.get("requests") or []
    if not enabled:
        return {"approved": False, "status": "not_attempted", "reason": "batch execution disabled"}
    if manual_approval_required:
        return {"approved": False, "status": "not_attempted", "reason": "manual approval required"}
    if not validation_result.get("approved"):
        return {"approved": False, "status": "not_attempted", "reason": "batch validation not approved"}
    if not requests_data:
        return {"approved": False, "status": "not_attempted", "reason": "no batch requests"}

    requests = [CreateOrderRequest(**request) for request in requests_data]
    response = await execution_client.execute_order_batch(requests, correlation_id)
    data = response.data or {}
    if hasattr(data, "model_dump"):
        data = data.model_dump(mode="json")
    return {
        "approved": bool((data or {}).get("approved")),
        "status": "attempted",
        "execution": data,
    }

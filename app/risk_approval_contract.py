from __future__ import annotations

import uuid
import datetime
from typing import Any, Dict, Optional, Union

from . import config


class RiskApprovalContractError(RuntimeError):
    pass


def _risk_data(trade_decision: Dict[str, Any]) -> Dict[str, Any]:
    return ((trade_decision.get("risk_agent_response") or {}).get("data") or {})


def choose_risk_approval_id(trade_decision: Dict[str, Any], correlation_id: str) -> str:
    data = _risk_data(trade_decision)
    approval_id = data.get("risk_approval_id") or data.get("approval_id") or trade_decision.get("risk_approval_id")
    if approval_id:
        return str(approval_id)
    return f"risk-{correlation_id}-{trade_decision.get('symbol', 'unknown')}-{uuid.uuid4().hex[:8]}"


def approval_expires_at(now: Optional[datetime.datetime] = None) -> str:
    now = now or datetime.datetime.now(datetime.timezone.utc)
    return (now + datetime.timedelta(minutes=config.RISK_APPROVAL_TTL_MINUTES)).isoformat()


async def persist_risk_approval(
    *,
    db_client: Any,
    trade_decision: Dict[str, Any],
    account_id: Union[int, str],
    correlation_id: str,
) -> str:
    if not trade_decision or not trade_decision.get("approved"):
        raise RiskApprovalContractError("Cannot persist risk approval for a rejected or missing trade decision.")

    quantity = int(trade_decision.get("position_size") or 0)
    if quantity <= 0:
        raise RiskApprovalContractError("Cannot persist risk approval with zero approved quantity.")

    action = str(trade_decision.get("action") or "").lower()
    side = "buy" if "buy" in action else "sell" if "sell" in action else None
    if side is None:
        raise RiskApprovalContractError(f"Unsupported approved action for risk approval: {action}")

    approval_id = choose_risk_approval_id(trade_decision, correlation_id)
    payload = {
        "approval_id": approval_id,
        "account_id": account_id,
        "symbol": str(trade_decision.get("symbol") or "").upper(),
        "side": side,
        "approved_quantity": quantity,
        "expires_at": approval_expires_at(),
        "metadata": {
            "source": "manager_agent",
            "correlation_id": correlation_id,
            "risk_agent_response": trade_decision.get("risk_agent_response") or {},
            "guard_plan": trade_decision.get("guard_plan"),
            "session_risk_context": trade_decision.get("session_risk_context") or {},
        },
    }
    await db_client.create_risk_approval(payload, correlation_id)
    trade_decision["risk_approval_id"] = approval_id
    return approval_id

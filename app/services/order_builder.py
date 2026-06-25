"""Order construction helpers for Manager_Agent.

This module converts approved risk decisions into Execution_Agent order request
contracts. It does not submit orders or call broker/execution services.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, Dict, Union

from ..contracts import CreateOrderRequest

ClientOrderIdFactory = Callable[[], str]


def side_from_action(action: str) -> str:
    """Translate a manager/risk action into an order side."""
    return "buy" if "buy" in str(action or "").lower() else "sell"


def guard_plan_for_execution(decision: Dict[str, Any]) -> Dict[str, Any]:
    """Return an explicit or default guard plan for execution.

    The default mirrors the legacy Manager portfolio order guard behavior.
    """
    if decision.get("guard_plan"):
        return decision["guard_plan"]

    stop_loss = decision.get("stop_loss")
    return {
        "source": "manager_portfolio_default_guard",
        "stop_loss": float(stop_loss) if stop_loss is not None else None,
        "risk_amount": float(decision.get("risk_amount") or 0),
    }


def order_request_from_decision(
    decision: Dict[str, Any],
    account_id: Union[int, str],
    *,
    client_order_id_factory: ClientOrderIdFactory | None = None,
) -> CreateOrderRequest:
    """Build a `CreateOrderRequest` from an approved risk decision.

    `client_order_id_factory` is injectable to make tests deterministic. In
    production it defaults to `uuid.uuid4()`.
    """
    quantity = int(decision.get("position_size") or decision.get("final_quantity") or 0)
    client_order_id = (
        client_order_id_factory()
        if client_order_id_factory is not None
        else str(uuid.uuid4())
    )

    return CreateOrderRequest(
        symbol=str(decision["symbol"]).upper(),
        side=side_from_action(decision.get("action")),
        order_type="market",
        quantity=quantity,
        price=float(decision.get("entry_price") or 0),
        client_order_id=client_order_id,
        account_id=account_id,
        strategy_bucket=(decision.get("stock_risk_context") or {}).get("strategy_bucket", "unassigned"),
        risk_approval_id=str(decision["risk_approval_id"]),
        final_quantity=quantity,
        guard_plan=guard_plan_for_execution(decision),
    )

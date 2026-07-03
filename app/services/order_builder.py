"""Order construction helpers for Manager_Agent.

This module converts approved risk decisions into Execution_Agent order request
contracts. It does not submit orders or call broker/execution services.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, Dict, Optional, Union

from pydantic import ValidationError

from ..contracts import CreateOrderRequest, TradePlan

ClientOrderIdFactory = Callable[[], str]


class OrderBuildError(ValueError):
    """Raised when Manager refuses to build an unsafe execution order."""


def side_from_action(action: str) -> str:
    """Translate an explicit manager/risk action into an order side."""
    normalized = str(action or "").strip().lower()
    if normalized in {"buy", "strong_buy"}:
        return "buy"
    if normalized in {"sell", "strong_sell"}:
        return "sell"
    raise OrderBuildError(f"unsupported execution action: {action!r}")


def strategy_bucket_from_decision(decision: Dict[str, Any]) -> str:
    """Return the best available strategy bucket from a risk decision.

    Older Manager paths placed the bucket under `stock_risk_context`; newer
    portfolio-first paths can also carry it at the decision root or inside
    portfolio metadata. Keep all fallbacks so the bucket does not regress to
    `unassigned` before it reaches Database/Execution.
    """
    stock_context = decision.get("stock_risk_context") or {}
    portfolio_context = decision.get("portfolio_context") or {}
    metadata = decision.get("metadata") or {}
    bucket = (
        stock_context.get("strategy_bucket")
        or decision.get("strategy_bucket")
        or portfolio_context.get("strategy_bucket")
        or portfolio_context.get("bucket")
        or metadata.get("strategy_bucket")
        or metadata.get("bucket")
        or "unassigned"
    )
    return str(bucket or "unassigned")


def _positive_float(value: Any, field_name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise OrderBuildError(f"{field_name} must be a number") from exc
    if result <= 0:
        raise OrderBuildError(f"{field_name} must be greater than zero")
    return result


def guard_plan_for_execution(decision: Dict[str, Any]) -> Dict[str, Any]:
    """Return a complete broker-side guard plan for execution."""
    if decision.get("guard_plan"):
        guard_plan = dict(decision["guard_plan"])
    else:
        guard_plan = {
            "source": "manager_portfolio_default_guard",
            "trigger_price": decision.get("trigger_price") or decision.get("stop_loss"),
            "take_profit_price": decision.get("take_profit_price") or decision.get("take_profit"),
            "risk_amount": float(decision.get("risk_amount") or 0),
        }

    trigger_price = guard_plan.get("trigger_price") or guard_plan.get("stop_price") or guard_plan.get("stop_loss")
    take_profit_price = guard_plan.get("take_profit_price") or guard_plan.get("take_profit")
    guard_plan["trigger_price"] = _positive_float(trigger_price, "guard_plan.trigger_price")
    guard_plan["take_profit_price"] = _positive_float(take_profit_price, "guard_plan.take_profit_price")
    return guard_plan


def _trade_plan_from_decision(decision: Dict[str, Any]) -> Optional[TradePlan]:
    """Return a validated TradePlan when a decision carries a usable snapshot."""
    trade_plan = decision.get("trade_plan")
    if not isinstance(trade_plan, dict):
        return None
    try:
        plan = TradePlan.model_validate(trade_plan)
    except ValidationError as exc:
        decision["trade_plan_order_error"] = str(exc)
        return None

    risk_approval_id = decision.get("risk_approval_id") or plan.risk_approval_id
    if risk_approval_id:
        plan.risk_approval_id = str(risk_approval_id)
        decision["risk_approval_id"] = str(risk_approval_id)
        trade_plan["risk_approval_id"] = str(risk_approval_id)
    return plan


def order_request_from_trade_plan_decision(decision: Dict[str, Any]) -> Optional[CreateOrderRequest]:
    """Build an execution order from TradePlan when the decision has one.

    Returns None when no TradePlan snapshot is present. If a TradePlan exists but
    is incomplete or not execution-ready, fail closed and surface the reason.
    """
    if not isinstance(decision.get("trade_plan"), dict):
        return None
    plan = _trade_plan_from_decision(decision)
    if plan is None:
        raise OrderBuildError(decision.get("trade_plan_order_error") or "invalid trade_plan snapshot")
    if not plan.risk_approval_id:
        decision["trade_plan_order_error"] = "risk_approval_id is required before creating an execution order"
        raise OrderBuildError(decision["trade_plan_order_error"])
    try:
        order = plan.to_execution_order()
    except Exception as exc:
        decision["trade_plan_order_error"] = str(exc)
        raise OrderBuildError(str(exc)) from exc
    decision["order_source"] = "trade_plan"
    return order


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
    trade_plan_order = order_request_from_trade_plan_decision(decision)
    if trade_plan_order is not None:
        return trade_plan_order

    quantity = int(decision.get("position_size") or decision.get("final_quantity") or 0)
    if quantity <= 0:
        raise OrderBuildError("final_quantity or position_size must be greater than zero")
    risk_approval_id = decision.get("risk_approval_id")
    if not risk_approval_id:
        raise OrderBuildError("risk_approval_id is required before creating an execution order")

    entry_price = _positive_float(decision.get("entry_price"), "entry_price")
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
        price=entry_price,
        client_order_id=client_order_id,
        account_id=account_id,
        strategy_bucket=strategy_bucket_from_decision(decision),
        risk_approval_id=str(risk_approval_id),
        final_quantity=quantity,
        guard_plan=guard_plan_for_execution(decision),
    )

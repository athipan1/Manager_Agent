"""TradePlan construction helpers for Manager_Agent.

This module translates Manager analysis + risk decision outputs into the new
canonical TradePlan contract. It is intentionally side-effect free: it does not
call Risk_Agent, Database_Agent, or Execution_Agent.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from .. import config
from ..contracts import OrderSide, OrderType, TradePlan, TradePlanExit, TradePlanRisk
from ..logger import report_logger
from .analysis_service import extract_current_price_and_stop
from .order_builder import side_from_action, strategy_bucket_from_decision
from .serialization_service import jsonable, normalize_score


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _positive_or_none(value: Any) -> Optional[float]:
    numeric = _as_float(value, 0.0)
    return numeric if numeric > 0 else None


def _safe_quantity(decision: Optional[Dict[str, Any]], default: int = 1) -> int:
    decision = decision or {}
    quantity = int(
        _as_float(
            decision.get("position_size")
            or decision.get("final_quantity")
            or decision.get("quantity")
            or default,
            default,
        )
    )
    return max(1, quantity)


def _risk_amount(decision: Optional[Dict[str, Any]], entry_price: float, stop_loss: Optional[float], quantity: int) -> float:
    decision = decision or {}
    explicit = _positive_or_none(decision.get("risk_amount"))
    if explicit is not None:
        return explicit
    if stop_loss is not None and entry_price > 0 and quantity > 0:
        return abs(entry_price - stop_loss) * quantity
    # Conservative fallback: keep the contract valid even when a rejected decision
    # lacks sizing/protection details. Rejected plans stay advisory/audit-only.
    return max(0.01, entry_price * quantity * _as_float(config.RISK_PER_TRADE, 0.01))


def _position_value(decision: Optional[Dict[str, Any]], entry_price: float, quantity: int) -> Optional[float]:
    decision = decision or {}
    approved_value = _positive_or_none(decision.get("approved_value"))
    if approved_value is not None:
        return approved_value
    return entry_price * quantity if entry_price > 0 and quantity > 0 else None


def _confidence_score(analysis_result: Dict[str, Any]) -> float:
    details = analysis_result.get("details")
    scores = []
    if details and getattr(details, "technical", None):
        scores.append(normalize_score(details.technical.score))
    if details and getattr(details, "fundamental", None):
        scores.append(normalize_score(details.fundamental.score))
    if scores:
        return round(sum(scores) / len(scores), 4)
    return 0.0


def _expected_r(entry_price: float, stop_loss: Optional[float], take_profit: Optional[float]) -> Optional[float]:
    if not stop_loss or not take_profit or entry_price <= 0:
        return None
    risk = abs(entry_price - stop_loss)
    reward = abs(take_profit - entry_price)
    if risk <= 0:
        return None
    return round(reward / risk, 4)


def build_trade_plan(
    *,
    analysis_result: Dict[str, Any],
    trade_decision: Optional[Dict[str, Any]],
    account_id: Union[int, str],
    correlation_id: str,
    dry_run: bool = False,
    source: str = "single_analysis",
) -> TradePlan:
    """Build a canonical TradePlan from Manager analysis and risk output.

    The builder supports approved and rejected decisions. Rejected plans remain
    useful for audit because they capture what would have been traded and why the
    decision did not advance.
    """
    decision = trade_decision or {}
    ticker = str(analysis_result.get("ticker") or decision.get("symbol") or "UNKNOWN").upper()
    verdict = str(analysis_result.get("final_verdict") or decision.get("action") or "hold").lower()
    side = OrderSide(side_from_action(decision.get("action") or verdict))
    entry_price, technical_stop = extract_current_price_and_stop(analysis_result)
    entry_price = _as_float(decision.get("entry_price"), entry_price)
    if entry_price <= 0:
        # Keep the audit contract valid when downstream analysis did not return a
        # price. Risk should still reject these before execution.
        entry_price = 0.01

    stop_loss = _positive_or_none(decision.get("stop_loss")) or _positive_or_none(technical_stop)
    if stop_loss is None:
        stop_pct = _as_float(config.STOP_LOSS_PERCENTAGE, 0.10)
        stop_loss = entry_price * (1 - stop_pct) if side == OrderSide.BUY else entry_price * (1 + stop_pct)

    quantity = _safe_quantity(decision)
    position_value = _position_value(decision, entry_price, quantity)
    risk_amount = _risk_amount(decision, entry_price, stop_loss, quantity)
    account_equity = _positive_or_none(decision.get("portfolio_value") or decision.get("account_equity"))
    risk_pct = risk_amount / account_equity if account_equity else _as_float(config.RISK_PER_TRADE, 0.01)
    risk_per_share = abs(entry_price - stop_loss) if stop_loss is not None else None
    position_pct = (position_value / account_equity) if position_value is not None and account_equity else None

    take_profit = _positive_or_none(decision.get("take_profit") or decision.get("take_profit_price"))
    plan_exit = TradePlanExit(
        stop_loss=stop_loss,
        take_profit=take_profit,
        trailing_stop_pct=_positive_or_none(decision.get("trailing_stop_pct")),
        break_even_trigger_r=_positive_or_none(decision.get("break_even_trigger_r")),
        partial_exit_pct=_positive_or_none(decision.get("partial_exit_pct")),
        time_stop_minutes=decision.get("time_stop_minutes"),
        exit_reason=decision.get("exit_reason"),
    )

    approved = bool(decision.get("approved"))
    risk_approval_id = decision.get("risk_approval_id")
    status = "risk_approved" if approved and risk_approval_id else "risk_pending" if approved else "rejected"

    plan = TradePlan(
        plan_id=str(risk_approval_id or f"plan-{correlation_id}-{ticker}"),
        correlation_id=correlation_id,
        source=source,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        account_id=account_id,
        symbol=ticker,
        side=side,
        order_type=OrderType.MARKET,
        entry_price=entry_price,
        quantity=quantity,
        final_quantity=decision.get("final_quantity") or quantity,
        strategy=str(decision.get("strategy") or verdict),
        strategy_bucket=strategy_bucket_from_decision(decision),  # type: ignore[arg-type]
        final_verdict=verdict,
        confidence_score=_confidence_score(analysis_result),
        expected_r=_expected_r(entry_price, stop_loss, take_profit),
        risk=TradePlanRisk(
            account_equity=account_equity,
            cash_available=_positive_or_none(decision.get("cash_available")),
            max_loss_amount=risk_amount,
            max_loss_pct=max(0.000001, min(risk_pct, 1.0)),
            risk_per_share=risk_per_share,
            position_value=position_value,
            position_pct=position_pct,
            reward_risk_ratio=_expected_r(entry_price, stop_loss, take_profit),
            session_risk_loaded=bool(decision.get("session_risk_context")),
            portfolio_context_loaded=bool(decision.get("portfolio_context") or decision.get("stock_risk_context")),
        ),
        exit=plan_exit,
        risk_approval_id=str(risk_approval_id) if risk_approval_id else None,
        manual_approval_required=config.MANUAL_APPROVAL_REQUIRED,
        dry_run=dry_run,
        reasons=[str(decision.get("reason"))] if decision.get("reason") else [],
        guard_plan=decision.get("guard_plan") or {},
        metadata={
            "approved": approved,
            "trade_decision": jsonable(decision),
            "analysis_status": analysis_result.get("status"),
        },
    )
    return plan


def attach_trade_plan_to_decision(
    *,
    analysis_result: Dict[str, Any],
    trade_decision: Optional[Dict[str, Any]],
    account_id: Union[int, str],
    correlation_id: str,
    dry_run: bool = False,
    source: str = "single_analysis",
) -> Optional[TradePlan]:
    """Build and attach a JSON-friendly TradePlan snapshot to a decision.

    Attachment is deliberately non-blocking: an unexpected TradePlan validation
    issue should be visible in audit metadata, but it should not break the legacy
    Manager path during the staged migration.
    """
    if trade_decision is None:
        return None
    try:
        plan = build_trade_plan(
            analysis_result=analysis_result,
            trade_decision=trade_decision,
            account_id=account_id,
            correlation_id=correlation_id,
            dry_run=dry_run,
            source=source,
        )
    except Exception as exc:
        trade_decision["trade_plan_error"] = str(exc)
        report_logger.warning(
            f"Failed to attach trade plan for {analysis_result.get('ticker')}: {exc}, "
            f"correlation_id={correlation_id}"
        )
        return None
    trade_decision["trade_plan"] = plan.model_dump(mode="json")
    trade_decision["trade_plan_id"] = plan.plan_id
    return plan

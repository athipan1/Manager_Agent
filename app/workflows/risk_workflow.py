"""Risk workflow helpers for Manager_Agent.

This module centralizes Manager-side risk decision orchestration. It builds the
same inputs that legacy `app.main` passes to local risk helpers, but does not
execute orders.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Union

from .. import config
from ..config_manager import config_manager
from ..portfolio_risk_manager import assess_portfolio_trades
from ..risk_manager import assess_trade
from ..stock_guard import StockGuardError, validate_trade_action
from ..services.analysis_service import extract_current_price_and_stop
from ..services.exposure_service import position_exposure, total_position_exposure
from .execution_workflow import ensure_risk_approval_id

TRADEABLE_VERDICTS = {"buy", "sell", "strong_buy", "strong_sell"}


def is_tradeable_verdict(verdict: str) -> bool:
    """Return whether a final verdict should be passed into risk evaluation."""
    return str(verdict or "").lower() in TRADEABLE_VERDICTS


def rejected_trade_decision(
    *,
    symbol: str,
    action: str,
    reason: str,
    session_risk_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a standard rejected trade decision payload."""
    return {
        "approved": False,
        "reason": reason,
        "symbol": symbol,
        "action": action,
        "position_size": 0,
        "session_risk_context": session_risk_context,
    }


def evaluate_single_trade_risk(
    *,
    ticker: str,
    final_verdict: str,
    analysis_result: Dict[str, Any],
    balance: Any,
    positions: Iterable[Any],
    context_value: Decimal,
    session_context: Dict[str, Any],
    correlation_id: str,
) -> Dict[str, Any]:
    """Evaluate risk for a single symbol analysis result.

    This preserves the legacy Manager behavior:

    - non-tradeable verdicts are not expected here
    - stock guard failures return rejected decisions
    - approved/rejected decisions always receive a risk approval id
    """
    positions = list(positions or [])
    portfolio_value = balance.cash_balance if balance else 0
    current_position = next((position for position in positions if position.symbol == ticker), None)

    try:
        validate_trade_action(ticker, final_verdict, current_position)
    except StockGuardError as guard_exc:
        decision = rejected_trade_decision(
            symbol=ticker,
            action=final_verdict,
            reason=str(guard_exc),
            session_risk_context=session_context,
        )
        ensure_risk_approval_id(decision, correlation_id)
        return decision

    entry_price, technical_stop = extract_current_price_and_stop(analysis_result)
    decision = assess_trade(
        portfolio_value=Decimal(portfolio_value),
        risk_per_trade=Decimal(config_manager.get("RISK_PER_TRADE")),
        fixed_stop_loss_pct=Decimal(config_manager.get("STOP_LOSS_PERCENTAGE")),
        enable_technical_stop=config_manager.get("ENABLE_TECHNICAL_STOP"),
        max_position_pct=Decimal(config_manager.get("MAX_POSITION_PERCENTAGE")),
        symbol=ticker,
        action=final_verdict,
        entry_price=Decimal(entry_price),
        technical_stop_loss=Decimal(technical_stop) if technical_stop is not None else None,
        current_position_size=current_position.quantity if current_position else 0,
        current_symbol_exposure=position_exposure(current_position),
        current_total_exposure=total_position_exposure(positions),
        open_orders_exposure=context_value,
        margin_multiplier=Decimal(str(config.DEFAULT_MARGIN_MULTIPLIER)),
        session_risk_context=session_context,
    )
    ensure_risk_approval_id(decision, correlation_id)
    return decision


def evaluate_portfolio_risk(
    *,
    analysis_results: List[Dict[str, Any]],
    cash_balance: Decimal,
    existing_positions: Iterable[Any],
    context_value: Decimal,
    session_context: Dict[str, Any],
    correlation_id: str,
) -> List[Dict[str, Any]]:
    """Evaluate portfolio risk for multiple analysis results."""
    decisions = assess_portfolio_trades(
        analysis_results=analysis_results,
        cash_balance=Decimal(cash_balance),
        existing_positions=list(existing_positions or []),
        per_request_risk_budget=Decimal(config_manager.get("PER_REQUEST_RISK_BUDGET", "0.1")),
        max_total_exposure=Decimal(config_manager.get("MAX_TOTAL_EXPOSURE", "0.8")),
        risk_per_trade=Decimal(config_manager.get("RISK_PER_TRADE", "0.01")),
        fixed_stop_loss_pct=Decimal(config_manager.get("STOP_LOSS_PERCENTAGE", "0.1")),
        enable_technical_stop=config_manager.get("ENABLE_TECHNICAL_STOP", True),
        max_position_pct=Decimal(config_manager.get("MAX_POSITION_PERCENTAGE", "0.2")),
        min_position_value=Decimal(config_manager.get("MIN_POSITION_VALUE", "500")),
        open_orders_exposure=context_value,
        margin_multiplier=Decimal(str(config.DEFAULT_MARGIN_MULTIPLIER)),
        session_risk_context=session_context,
    )
    for decision in decisions:
        ensure_risk_approval_id(decision, correlation_id)
    return decisions


def approved_trades(decisions: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return only approved risk decisions."""
    return [decision for decision in decisions if decision.get("approved")]

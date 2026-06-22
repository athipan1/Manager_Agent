import os
from decimal import Decimal, ROUND_FLOOR
from typing import Any, Dict, Optional

from . import config
from .risk_agent_client import evaluate_risk


"""
Risk payload exposure contract:

- current_symbol_exposure: existing filled position exposure for the target symbol only.
- current_total_exposure: existing filled portfolio position exposure only; it must not include open/pending orders.
- open_orders_exposure: outstanding order exposure for pending/placed/partially-filled orders.
- requested_quantity: desired quantity for the new order being reviewed.
- session_risk_context: daily/weekly PnL, trade counters, cooldown age, and emergency halt state.
- stock_risk_context: asset_class, sector, owned quantity, and current sector exposure.

Risk_Agent owns the projected exposure calculation:
current_total_exposure + open_orders_exposure + new_order_position_value.
"""


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None:
            return default
        return Decimal(str(value))
    except Exception:
        return default


def _normalise_action(action: str) -> str:
    action_lower = str(action or "hold").lower()
    if action_lower in {"buy", "strong_buy"}:
        return "buy"
    if action_lower in {"sell", "strong_sell", "short", "cover"}:
        return "sell"
    return "hold"


def _default_protection_price(side: str, entry_price: Decimal, fixed_pct: Decimal) -> Decimal:
    if side == "buy":
        return entry_price * (Decimal("1") - fixed_pct)
    if side == "sell":
        return entry_price * (Decimal("1") + fixed_pct)
    return entry_price


def _floor_quantity(value: Decimal) -> int:
    if value <= Decimal("0"):
        return 0
    return int(value.to_integral_value(rounding=ROUND_FLOOR))


def _default_requested_quantity(*, side: str, portfolio_value: Decimal, risk_per_trade: Decimal, max_position_pct: Decimal, entry_price: Decimal, protection_price: Decimal, current_position_size: int) -> int:
    if side == "sell" and current_position_size:
        return max(0, int(abs(current_position_size)))

    per_unit_risk = abs(entry_price - protection_price)
    risk_budget = portfolio_value * risk_per_trade
    max_position_value = portfolio_value * max_position_pct

    risk_limited_qty = _floor_quantity(risk_budget / per_unit_risk) if per_unit_risk > 0 else 0
    value_limited_qty = _floor_quantity(max_position_value / entry_price) if entry_price > 0 else 0
    candidates = [qty for qty in (risk_limited_qty, value_limited_qty) if qty > 0]
    return min(candidates) if candidates else 0


def _build_result(approved: bool, reason: str, symbol: str, action: str, entry_price: Decimal, position_size: int = 0, protection_price: Optional[Decimal] = None, risk_response: Optional[Dict[str, Any]] = None, session_risk_context: Optional[Dict[str, Any]] = None, stock_risk_context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    risk_amount = Decimal("0")
    if protection_price is not None and position_size > 0:
        risk_amount = abs(entry_price - protection_price) * Decimal(position_size)
    return {
        "approved": approved,
        "reason": reason,
        "symbol": symbol,
        "action": action,
        "entry_price": entry_price,
        "position_size": int(position_size or 0),
        "stop_loss": protection_price,
        "risk_amount": risk_amount,
        "risk_agent_response": risk_response or {},
        "guard_plan": (risk_response or {}).get("data", {}).get("guard_plan"),
        "session_risk_context": session_risk_context or {},
        "stock_risk_context": stock_risk_context or {},
    }


def _default_stock_context(current_position_size: int) -> Dict[str, Any]:
    return {
        "asset_class": config.ASSET_CLASS,
        "owned_quantity": float(abs(int(current_position_size or 0))),
        "current_sector_exposure": 0.0,
    }


def _normalize_stock_context(stock_risk_context: Dict[str, Any], *, current_position_size: int, symbol_exposure: Decimal) -> Dict[str, Any]:
    context = {**_default_stock_context(current_position_size), **(stock_risk_context or {})}
    context.setdefault("asset_class", config.ASSET_CLASS)
    context.setdefault("owned_quantity", float(abs(int(current_position_size or 0))))
    if _as_decimal(context.get("current_symbol_exposure"), Decimal("0")) <= Decimal("0") and symbol_exposure > Decimal("0"):
        context["current_symbol_exposure"] = float(symbol_exposure)
    if _as_decimal(context.get("current_sector_exposure"), Decimal("0")) <= Decimal("0") and symbol_exposure > Decimal("0"):
        context["current_sector_exposure"] = float(symbol_exposure)
    return context


def assess_trade(
    portfolio_value: Decimal,
    risk_per_trade: Decimal,
    fixed_stop_loss_pct: Decimal,
    enable_technical_stop: bool,
    max_position_pct: Decimal,
    symbol: str,
    action: str,
    entry_price: Decimal,
    technical_stop_loss: Optional[Decimal] = None,
    current_position_size: int = 0,
    atr_value: Optional[Decimal] = None,
    atr_multiplier: Decimal = Decimal("2.0"),
    take_profit_price: Optional[Decimal] = None,
    reward_multiplier: Optional[Decimal] = None,
    min_risk_reward_ratio: Optional[Decimal] = None,
    current_symbol_exposure: Optional[Decimal] = None,
    current_total_exposure: Optional[Decimal] = None,
    open_orders_exposure: Optional[Decimal] = None,
    margin_multiplier: Optional[Decimal] = None,
    requested_quantity: Optional[int] = None,
    session_risk_context: Optional[Dict[str, Any]] = None,
    stock_risk_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    side = _normalise_action(action)
    session_risk_context = session_risk_context or {}
    derived_symbol_exposure = abs(Decimal(int(current_position_size or 0)) * entry_price)
    symbol_exposure = _as_decimal(current_symbol_exposure, derived_symbol_exposure)
    stock_risk_context = _normalize_stock_context(stock_risk_context or {}, current_position_size=current_position_size, symbol_exposure=symbol_exposure)

    if side == "hold":
        return _build_result(False, "Risk_Agent check skipped because action is hold or unsupported.", symbol, str(action).lower(), entry_price, session_risk_context=session_risk_context, stock_risk_context=stock_risk_context)
    if portfolio_value <= Decimal("0"):
        return _build_result(False, "Risk_Agent check failed: portfolio_value must be greater than zero.", symbol, side, entry_price, session_risk_context=session_risk_context, stock_risk_context=stock_risk_context)
    if entry_price <= Decimal("0"):
        return _build_result(False, "Risk_Agent check failed: entry_price must be greater than zero.", symbol, side, entry_price, session_risk_context=session_risk_context, stock_risk_context=stock_risk_context)

    if not config.TRADING_ENABLED:
        return _build_result(False, f"Global kill switch active: TRADING_ENABLED=false. Mode={config.TRADING_MODE}.", symbol, side, entry_price, session_risk_context=session_risk_context, stock_risk_context=stock_risk_context)

    if config.TRADING_MODE not in {"PAPER", "LIVE"}:
        return _build_result(False, f"Invalid TRADING_MODE={config.TRADING_MODE}; rejecting trade.", symbol, side, entry_price, session_risk_context=session_risk_context, stock_risk_context=stock_risk_context)
    if config.TRADING_MODE == "LIVE" and not config.ALLOW_LIVE_TRADING:
        return _build_result(False, "LIVE mode requires ALLOW_LIVE_TRADING=true; rejecting trade.", symbol, side, entry_price, session_risk_context=session_risk_context, stock_risk_context=stock_risk_context)
    if config.TRADING_MODE == "LIVE" and (current_symbol_exposure is None or current_total_exposure is None or open_orders_exposure is None):
        return _build_result(False, "LIVE risk context incomplete: symbol exposure, total exposure, and open orders exposure are required.", symbol, side, entry_price, session_risk_context=session_risk_context, stock_risk_context=stock_risk_context)
    if config.TRADING_MODE == "LIVE" and not session_risk_context:
        return _build_result(False, "LIVE session risk context incomplete: daily/weekly loss and cooldown counters are required.", symbol, side, entry_price, session_risk_context=session_risk_context, stock_risk_context=stock_risk_context)

    protection_price = technical_stop_loss if enable_technical_stop and technical_stop_loss is not None and technical_stop_loss > Decimal("0") else _default_protection_price(side, entry_price, fixed_stop_loss_pct)
    if side == "buy" and protection_price >= entry_price:
        protection_price = _default_protection_price(side, entry_price, fixed_stop_loss_pct)
    if side == "sell" and protection_price <= entry_price:
        protection_price = _default_protection_price(side, entry_price, fixed_stop_loss_pct)

    total_exposure = _as_decimal(current_total_exposure, symbol_exposure)
    pending_exposure = _as_decimal(open_orders_exposure, Decimal("0"))
    margin = _as_decimal(margin_multiplier, Decimal(str(config.DEFAULT_MARGIN_MULTIPLIER)))

    if symbol_exposure < 0 or total_exposure < 0 or pending_exposure < 0:
        return _build_result(False, "Risk_Agent check failed: exposure values must be non-negative.", symbol, side, entry_price, protection_price=protection_price, session_risk_context=session_risk_context, stock_risk_context=stock_risk_context)
    if margin <= Decimal("0"):
        return _build_result(False, "Risk_Agent check failed: margin/leverage multiplier must be greater than zero.", symbol, side, entry_price, protection_price=protection_price, session_risk_context=session_risk_context, stock_risk_context=stock_risk_context)

    desired_quantity = int(requested_quantity) if requested_quantity is not None else _default_requested_quantity(side=side, portfolio_value=portfolio_value, risk_per_trade=risk_per_trade, max_position_pct=max_position_pct, entry_price=entry_price, protection_price=protection_price, current_position_size=current_position_size)
    desired_quantity = max(0, desired_quantity)

    payload = {
        "account_id": os.getenv("DEFAULT_ACCOUNT_ID", "1"),
        "symbol": symbol,
        "side": side,
        "entry_price": _as_float(entry_price),
        "protection_price": _as_float(protection_price),
        "requested_quantity": desired_quantity,
        "equity": _as_float(portfolio_value),
        "current_symbol_exposure": _as_float(symbol_exposure),
        "current_total_exposure": _as_float(total_exposure),
        "open_orders_exposure": _as_float(pending_exposure),
        "margin_multiplier": _as_float(margin, 1.0),
        "trading_mode": config.TRADING_MODE,
        **stock_risk_context,
        **session_risk_context,
    }

    try:
        risk_response = evaluate_risk(payload)
    except Exception as exc:
        return _build_result(False, f"Risk_Agent unavailable, circuit open, or returned invalid response: {exc}", symbol, side, entry_price, protection_price=protection_price, session_risk_context=session_risk_context, stock_risk_context=stock_risk_context)

    data = risk_response.get("data") or {}
    approved = bool(data.get("approved")) and str(risk_response.get("status", "")).lower() == "approved"
    final_quantity = int(data.get("final_quantity") or data.get("approved_quantity") or 0)
    reason = "Approved by external Risk_Agent." if approved else f"Rejected by external Risk_Agent: {data.get('violations') or risk_response.get('error')}"
    return _build_result(approved, reason, symbol, side, entry_price, final_quantity if approved else 0, protection_price, risk_response, session_risk_context, stock_risk_context)
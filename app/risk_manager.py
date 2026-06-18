import os
from decimal import Decimal
from typing import Any, Dict, Optional

from .risk_agent_client import evaluate_risk


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
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


def _build_result(approved: bool, reason: str, symbol: str, action: str, entry_price: Decimal, position_size: int = 0, protection_price: Optional[Decimal] = None, risk_response: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    risk_amount = Decimal("0")
    if protection_price is not None and position_size > 0:
        risk_amount = abs(entry_price - protection_price) * Decimal(position_size)
    return {"approved": approved, "reason": reason, "symbol": symbol, "action": action, "entry_price": entry_price, "position_size": int(position_size or 0), "stop_loss": protection_price, "risk_amount": risk_amount, "risk_agent_response": risk_response or {}, "guard_plan": (risk_response or {}).get("data", {}).get("guard_plan")}


def assess_trade(portfolio_value: Decimal, risk_per_trade: Decimal, fixed_stop_loss_pct: Decimal, enable_technical_stop: bool, max_position_pct: Decimal, symbol: str, action: str, entry_price: Decimal, technical_stop_loss: Optional[Decimal] = None, current_position_size: int = 0, atr_value: Optional[Decimal] = None, atr_multiplier: Decimal = Decimal("2.0"), take_profit_price: Optional[Decimal] = None, reward_multiplier: Optional[Decimal] = None, min_risk_reward_ratio: Optional[Decimal] = None) -> Dict[str, Any]:
    side = _normalise_action(action)
    if side == "hold":
        return _build_result(False, "Risk_Agent check skipped because action is hold or unsupported.", symbol, str(action).lower(), entry_price)
    if portfolio_value <= Decimal("0"):
        return _build_result(False, "Risk_Agent check failed: portfolio_value must be greater than zero.", symbol, side, entry_price)
    if entry_price <= Decimal("0"):
        return _build_result(False, "Risk_Agent check failed: entry_price must be greater than zero.", symbol, side, entry_price)

    protection_price = technical_stop_loss if enable_technical_stop and technical_stop_loss is not None and technical_stop_loss > Decimal("0") else _default_protection_price(side, entry_price, fixed_stop_loss_pct)
    if side == "buy" and protection_price >= entry_price:
        protection_price = _default_protection_price(side, entry_price, fixed_stop_loss_pct)
    if side == "sell" and protection_price <= entry_price:
        protection_price = _default_protection_price(side, entry_price, fixed_stop_loss_pct)

    payload = {"account_id": os.getenv("DEFAULT_ACCOUNT_ID", "1"), "symbol": symbol, "side": side, "entry_price": _as_float(entry_price), "protection_price": _as_float(protection_price), "requested_quantity": int(current_position_size or 0), "equity": _as_float(portfolio_value), "current_symbol_exposure": 0, "current_total_exposure": 0, "margin_multiplier": 1}

    try:
        risk_response = evaluate_risk(payload)
    except Exception as exc:
        return _build_result(False, f"Risk_Agent unavailable or returned invalid response: {exc}", symbol, side, entry_price, protection_price=protection_price)

    data = risk_response.get("data") or {}
    approved = bool(data.get("approved")) and str(risk_response.get("status", "")).lower() == "approved"
    final_quantity = int(data.get("final_quantity") or data.get("approved_quantity") or 0)
    reason = "Approved by external Risk_Agent." if approved else f"Rejected by external Risk_Agent: {data.get('violations') or risk_response.get('error')}"
    return _build_result(approved, reason, symbol, side, entry_price, final_quantity if approved else 0, protection_price, risk_response)

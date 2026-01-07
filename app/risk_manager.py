import os
import json
import csv
from datetime import datetime, timezone
from math import floor
from typing import Dict, Any, Optional
from decimal import Decimal

LOG_DIR = "logs"
JSON_LOG_FILE = os.path.join(LOG_DIR, "assessment_history.json")
CSV_LOG_FILE = os.path.join(LOG_DIR, "assessment_history.csv")

class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return str(o)
        return super(DecimalEncoder, self).default(o)

def _log_assessment_result(result: Dict[str, Any]):
    """Logs the result of a trade assessment to JSON and CSV files."""
    os.makedirs(LOG_DIR, exist_ok=True)

    log_entry = result.copy()
    log_entry["timestamp"] = datetime.now(timezone.utc).isoformat()

    with open(JSON_LOG_FILE, "a") as f:
        f.write(json.dumps(log_entry, cls=DecimalEncoder) + "\n")

    file_exists = os.path.isfile(CSV_LOG_FILE)
    with open(CSV_LOG_FILE, "a", newline="") as f:
        fieldnames = [
            "timestamp", "approved", "reason", "symbol", "action",
            "position_size", "stop_loss", "take_profit", "risk_reward_ratio",
            "risk_amount", "entry_price"
        ]
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')

        if not file_exists:
            writer.writeheader()

        writer.writerow(log_entry)

def _prepare_and_log_result(**kwargs):
    """Prepares the result dictionary and logs it before returning."""
    result = {
        "approved": kwargs.get("approved", False),
        "reason": kwargs.get("reason", "An unknown error occurred."),
        "symbol": kwargs.get("symbol"),
        "action": kwargs.get("action"),
        "entry_price": kwargs.get("entry_price"),
        "position_size": kwargs.get("position_size"),
        "stop_loss": kwargs.get("stop_loss"),
        "take_profit": kwargs.get("take_profit"),
        "risk_reward_ratio": kwargs.get("risk_reward_ratio"),
        "risk_amount": kwargs.get("risk_amount"),
    }
    final_result = {k: v for k, v in result.items() if v is not None}
    _log_assessment_result(final_result)
    return final_result


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
) -> Dict[str, Any]:
    """
    Assesses a trade based on a strict set of risk management rules.
    """
    action_lower = action.lower()

    if portfolio_value <= Decimal("0"):
        return _prepare_and_log_result(reason="Input validation failed: portfolio_value must be greater than 0.", symbol=symbol, action=action, position_size=0)
    if not Decimal("0") < risk_per_trade < Decimal("1"):
        return _prepare_and_log_result(reason="Input validation failed: risk_per_trade must be between 0 and 1.", symbol=symbol, action=action, position_size=0)
    if not Decimal("0") < max_position_pct <= Decimal("1"):
        return _prepare_and_log_result(reason="Input validation failed: max_position_pct must be between 0 and 1.", symbol=symbol, action=action, position_size=0)
    if entry_price <= Decimal("0") and action_lower in ["buy", "short"]:
        return _prepare_and_log_result(reason="Input validation failed: entry_price must be greater than 0 for buy/short actions.", symbol=symbol, action=action, position_size=0)

    if action_lower == "sell":
        if current_position_size > 0:
            return _prepare_and_log_result(approved=True, reason="Approval to sell existing position.", symbol=symbol, action=action_lower, position_size=current_position_size, risk_amount=Decimal("0.0"))
        else:
            return _prepare_and_log_result(reason="Sell rejected. No existing position to sell.", symbol=symbol, action=action_lower, position_size=0, risk_amount=Decimal("0.0"))

    if action_lower == "cover":
        if current_position_size < 0:
            return _prepare_and_log_result(approved=True, reason="Approval to cover existing short position.", symbol=symbol, action=action_lower, position_size=abs(current_position_size), risk_amount=Decimal("0.0"))
        else:
            return _prepare_and_log_result(reason="Cover rejected. No existing short position to cover.", symbol=symbol, action=action_lower, position_size=0, risk_amount=Decimal("0.0"))

    allowed_actions = ["buy", "sell", "short", "cover"]
    if action_lower not in allowed_actions:
        return _prepare_and_log_result(reason=f"Invalid action '{action}'. Allowed actions are: {', '.join(allowed_actions)}.", symbol=symbol, action=action, position_size=0)

    if action_lower not in ["buy", "short"]:
        return _prepare_and_log_result(reason=f"Action '{action}' is for closing positions, but no open position was found.", symbol=symbol, action=action_lower, position_size=0)

    final_stop_loss = Decimal("0.0")
    if action_lower == "buy":
        stop_loss_candidates = [entry_price * (Decimal("1") - fixed_stop_loss_pct)]
        if enable_technical_stop and technical_stop_loss is not None:
            stop_loss_candidates.append(technical_stop_loss)
        if atr_value is not None and atr_value > Decimal("0"):
            stop_loss_candidates.append(entry_price - (atr_value * atr_multiplier))
        final_stop_loss = max(c for c in stop_loss_candidates if c is not None)
        if final_stop_loss >= entry_price:
            return _prepare_and_log_result(reason=f"Stop loss ({final_stop_loss}) must be below entry price ({entry_price}) for a BUY action.", symbol=symbol, action=action_lower, position_size=0, stop_loss=final_stop_loss, risk_amount=Decimal("0"), entry_price=entry_price)

    elif action_lower == "short":
        stop_loss_candidates = [entry_price * (Decimal("1") + fixed_stop_loss_pct)]
        if enable_technical_stop and technical_stop_loss is not None:
            stop_loss_candidates.append(technical_stop_loss)
        if atr_value is not None and atr_value > Decimal("0"):
            stop_loss_candidates.append(entry_price + (atr_value * atr_multiplier))
        final_stop_loss = min(c for c in stop_loss_candidates if c is not None)
        if final_stop_loss <= entry_price:
            return _prepare_and_log_result(reason=f"Stop loss ({final_stop_loss}) must be above entry price ({entry_price}) for a SHORT action.", symbol=symbol, action=action_lower, position_size=0, stop_loss=final_stop_loss, risk_amount=Decimal("0"), entry_price=entry_price)

    risk_per_share = abs(entry_price - final_stop_loss)
    if risk_per_share <= Decimal("0"):
        return _prepare_and_log_result(reason="Risk per share is zero or negative. Cannot calculate position size.", symbol=symbol, action=action_lower, position_size=0, stop_loss=final_stop_loss, risk_amount=portfolio_value * risk_per_trade, entry_price=entry_price)

    final_take_profit = None
    risk_reward_ratio = None
    if take_profit_price is not None:
        final_take_profit = take_profit_price
    elif reward_multiplier is not None:
        final_take_profit = entry_price + (reward_multiplier * risk_per_share) if action_lower == 'buy' else entry_price - (reward_multiplier * risk_per_share)

    if final_take_profit is not None:
        reward_per_share = abs(final_take_profit - entry_price)
        risk_reward_ratio = reward_per_share / risk_per_share if risk_per_share > Decimal("0") else Decimal("inf")
        if min_risk_reward_ratio is not None and risk_reward_ratio < min_risk_reward_ratio:
            return _prepare_and_log_result(reason=f"Risk/Reward ratio ({risk_reward_ratio:.2f}) is below the minimum required ({min_risk_reward_ratio}).", symbol=symbol, action=action_lower, position_size=0, stop_loss=final_stop_loss, take_profit=final_take_profit, risk_reward_ratio=risk_reward_ratio, risk_amount=Decimal("0"), entry_price=entry_price)

    risk_amount_per_trade = portfolio_value * risk_per_trade
    position_size = floor(risk_amount_per_trade / risk_per_share)

    if position_size <= 0:
        return _prepare_and_log_result(reason=f"Calculated position size is {position_size}. Must be greater than zero.", symbol=symbol, action=action_lower, position_size=0, stop_loss=final_stop_loss, risk_amount=risk_amount_per_trade, entry_price=entry_price)

    position_value = Decimal(position_size) * entry_price
    max_allowed_value = portfolio_value * max_position_pct
    reason = "Trade approved by Risk Manager."

    if position_value > max_allowed_value:
        original_size = position_size
        position_size = floor(max_allowed_value / entry_price)
        if position_size <= 0:
            return _prepare_and_log_result(reason=f"Position size scaled down to {position_size} which is not a valid size.", symbol=symbol, action=action_lower, position_size=0, stop_loss=final_stop_loss, risk_amount=risk_amount_per_trade, entry_price=entry_price)
        risk_amount_per_trade = Decimal(position_size) * risk_per_share
        reason = f"Position size scaled down from {original_size} to {position_size} to respect max_position_pct."

    return _prepare_and_log_result(
        approved=True, reason=reason, symbol=symbol, action=action_lower,
        position_size=position_size, stop_loss=final_stop_loss,
        take_profit=final_take_profit, risk_reward_ratio=risk_reward_ratio,
        risk_amount=risk_amount_per_trade, entry_price=entry_price
    )

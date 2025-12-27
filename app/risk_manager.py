from math import floor
from typing import Dict, Any, Optional

def assess_trade(
    portfolio_value: float,
    risk_per_trade: float,
    fixed_stop_loss_pct: float,
    enable_technical_stop: bool,
    max_position_pct: float,
    symbol: str,
    action: str,
    entry_price: float,
    technical_stop_loss: Optional[float] = None,
    current_position_size: int = 0,
) -> Dict[str, Any]:
    """
    Assesses a trade based on a strict set of risk management rules.
    """
    # --- SELL LOGIC ---
    if action.lower() == "sell":
        if current_position_size > 0:
            return {
                "approved": True,
                "reason": "Approval to sell existing position.",
                "symbol": symbol,
                "action": "sell",
                "position_size": current_position_size,
                "stop_loss": None,
                "risk_amount": 0.0,
            }
        else:
            return {
                "approved": False,
                "reason": "Sell rejected. No existing position to sell.",
                "symbol": symbol,
                "action": "sell",
                "position_size": 0,
                "stop_loss": None,
                "risk_amount": 0.0,
            }

    # --- BUY LOGIC ---
    if action.lower() != "buy":
        return {
            "approved": False,
            "reason": f"Invalid action '{action}'. Only 'buy' or 'sell' allowed.",
            "position_size": 0,
        }

    # 1. Determine Stop Loss
    fixed_sl = entry_price * (1 - fixed_stop_loss_pct)
    final_stop_loss = fixed_sl

    if enable_technical_stop and technical_stop_loss is not None:
        # We want the stop loss that gives us the smallest risk per share (tightest stop)
        # as long as it respects the minimum fixed stop loss distance.
        # Therefore, we choose the higher value (closer to the entry price).
        if technical_stop_loss > fixed_sl:
            final_stop_loss = technical_stop_loss

    if final_stop_loss >= entry_price:
        return {
            "approved": False,
            "reason": f"Stop loss ({final_stop_loss}) must be below entry price ({entry_price}).",
            "symbol": symbol,
            "action": "buy",
            "position_size": 0,
            "stop_loss": final_stop_loss,
            "risk_amount": 0,
            "entry_price": entry_price,
        }

    # 2. Calculate Position Size
    risk_amount_per_trade = portfolio_value * risk_per_trade
    risk_per_share = entry_price - final_stop_loss

    if risk_per_share <= 0:
        return {
            "approved": False,
            "reason": "Risk per share is zero or negative. Cannot calculate position size.",
            "symbol": symbol,
            "action": "buy",
            "position_size": 0,
            "stop_loss": final_stop_loss,
            "risk_amount": risk_amount_per_trade,
            "entry_price": entry_price,
        }

    position_size = floor(risk_amount_per_trade / risk_per_share)

    if position_size <= 0:
        return {
            "approved": False,
            "reason": f"Calculated position size is {position_size}. Must be greater than zero.",
            "symbol": symbol,
            "action": "buy",
            "position_size": 0,
            "stop_loss": final_stop_loss,
            "risk_amount": risk_amount_per_trade,
            "entry_price": entry_price,
        }

    # 3. Check and Adjust for Max Position Value
    position_value = position_size * entry_price
    max_allowed_value = portfolio_value * max_position_pct
    reason = "Trade approved by Risk Manager."

    if position_value > max_allowed_value:
        original_size = position_size
        position_size = floor(max_allowed_value / entry_price)
        risk_amount_per_trade = position_size * risk_per_share
        reason = f"Position size scaled down from {original_size} to {position_size} to respect max_position_pct."

    # 4. Approval
    return {
        "approved": True,
        "reason": "Trade approved by Risk Manager.",
        "symbol": symbol,
        "action": "buy",
        "position_size": position_size,
        "stop_loss": final_stop_loss,
        "risk_amount": risk_amount_per_trade,
        "entry_price": entry_price,
    }

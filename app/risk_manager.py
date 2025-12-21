"""
Risk Management Module

This module provides functions for calculating trade sizes and managing risk
based on predefined strategies.
"""
from .models import AccountBalance

def calculate_position_size(
    balance: AccountBalance,
    risk_percentage: float,
    entry_price: float,
    stop_loss_price: float
) -> int:
    """
    Calculates the number of shares to buy or sell based on risk tolerance.

    Args:
        balance: The current account balance details.
        risk_percentage: The percentage of the account to risk on a single trade (e.g., 0.01 for 1%).
        entry_price: The price at which the asset is bought.
        stop_loss_price: The price at which the position is sold to prevent further losses.

    Returns:
        The number of shares to trade, as an integer. Returns 0 if risk is undefined.
    """
    if entry_price <= stop_loss_price:
        return 0  # Stop loss must be below entry for a buy

    risk_per_share = entry_price - stop_loss_price
    if risk_per_share <= 0:
        return 0

    amount_to_risk = balance.cash_balance * risk_percentage
    position_size = amount_to_risk / risk_per_share

    return int(position_size)

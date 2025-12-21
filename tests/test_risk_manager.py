import pytest
from app.risk_manager import calculate_position_size
from app.models import AccountBalance

def test_calculate_position_size_valid():
    """Test position size calculation with standard valid inputs."""
    balance = AccountBalance(cash_balance=100000)
    risk_percentage = 0.01
    entry_price = 150.0
    stop_loss_price = 145.0

    # Amount to risk = 100000 * 0.01 = 1000
    # Risk per share = 150 - 145 = 5
    # Position size = 1000 / 5 = 200

    assert calculate_position_size(balance, risk_percentage, entry_price, stop_loss_price) == 200

def test_calculate_position_size_zero_risk():
    """Test with zero risk percentage, expecting zero position size."""
    balance = AccountBalance(cash_balance=100000)
    risk_percentage = 0.0
    entry_price = 150.0
    stop_loss_price = 145.0

    assert calculate_position_size(balance, risk_percentage, entry_price, stop_loss_price) == 0

def test_calculate_position_size_invalid_stop_loss():
    """Test with a stop loss price higher than the entry price."""
    balance = AccountBalance(cash_balance=100000)
    risk_percentage = 0.01
    entry_price = 150.0
    stop_loss_price = 155.0  # Invalid SL

    assert calculate_position_size(balance, risk_percentage, entry_price, stop_loss_price) == 0

def test_calculate_position_size_no_risk_per_share():
    """Test with stop loss equal to entry price, which should prevent division by zero."""
    balance = AccountBalance(cash_balance=100000)
    risk_percentage = 0.01
    entry_price = 150.0
    stop_loss_price = 150.0

    assert calculate_position_size(balance, risk_percentage, entry_price, stop_loss_price) == 0

def test_calculate_position_size_float_result():
    """Test a scenario that results in a fractional position size, expecting an integer."""
    balance = AccountBalance(cash_balance=5000)
    risk_percentage = 0.02
    entry_price = 120.0
    stop_loss_price = 117.0

    # Amount to risk = 5000 * 0.02 = 100
    # Risk per share = 120 - 117 = 3
    # Position size = 100 / 3 = 33.33...

    assert calculate_position_size(balance, risk_percentage, entry_price, stop_loss_price) == 33

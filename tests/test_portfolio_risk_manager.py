import pytest
from app.portfolio_risk_manager import PortfolioRiskManager
from app.models import Position

@pytest.fixture
def manager():
    """Fixture for a PortfolioRiskManager with a standard setup."""
    positions = [
        Position(symbol="AAPL", quantity=10, average_cost=150, current_market_price=170),
        Position(symbol="GOOG", quantity=5, average_cost=2500, current_market_price=2700),
    ]
    # Total position value = (10 * 170) + (5 * 2700) = 1700 + 13500 = 15200
    # Let's say portfolio_value also includes 84800 in cash.
    return PortfolioRiskManager(
        portfolio_value=100000,
        existing_positions=positions,
        per_request_risk_budget=0.02,  # 2% of portfolio, so $2000
        max_total_exposure=0.5,  # 50% of portfolio, so $50000
        min_position_value=500,
    )

def test_initialization(manager: PortfolioRiskManager):
    """Test if the manager initializes correctly."""
    assert manager.portfolio_value == 100000
    assert manager.remaining_budget == 2000
    assert manager.max_total_exposure_value == 50000
    assert manager.current_exposure == 15200
    assert manager.approved_buys_value == 0.0

def test_evaluate_sell(manager: PortfolioRiskManager):
    """Test that a sell reduces the current exposure."""
    # Market value of 5 AAPL shares is 5 * 170 = 850
    sell_decision = {
        "approved": True,
        "action": "sell",
        "symbol": "AAPL",
        "position_size": 5,
    }
    manager.evaluate_sell(sell_decision)
    # Initial exposure was 15200. After sell, it should be 15200 - 850 = 14350.
    assert manager.current_exposure == 14350

def test_evaluate_buy_approved(manager: PortfolioRiskManager):
    """Test a standard buy approval."""
    buy_decision = {
        "approved": True,
        "risk_amount": 1000,
        "position_size": 50,
        "entry_price": 100,
    }
    final_decision = manager.evaluate_buy(buy_decision)

    assert final_decision["approved"]
    assert manager.remaining_budget == 1000  # 2000 - 1000
    assert manager.approved_buys_value == 5000 # 50 * 100

def test_evaluate_buy_rejected_due_to_exposure(manager: PortfolioRiskManager):
    """Test rejection when a buy exceeds max total exposure."""
    # Current exposure is 15200. Max is 50000.
    # This trade's value is 40 * 1000 = 40000.
    # 15200 + 40000 > 50000, so it should be rejected.
    buy_decision = {
        "approved": True,
        "risk_amount": 1500,
        "position_size": 40,
        "entry_price": 1000,
    }
    final_decision = manager.evaluate_buy(buy_decision)

    assert not final_decision["approved"]
    assert "exceeds max total portfolio exposure" in final_decision["reason"]
    # State should not change
    assert manager.remaining_budget == 2000
    assert manager.approved_buys_value == 0

def test_evaluate_buy_scaled_down_due_to_budget(manager: PortfolioRiskManager):
    """Test that a trade is scaled down if it exceeds the remaining budget."""
    # Required risk is 3000, but budget is only 2000.
    # Scaling factor should be 2000 / 3000 = 0.666...
    # Original size is 60. Scaled size should be int(60 * 0.666...) = 40.
    buy_decision = {
        "approved": True,
        "risk_amount": 3000,
        "position_size": 60,
        "entry_price": 200,
    }
    final_decision = manager.evaluate_buy(buy_decision)

    assert final_decision["approved"]
    assert "scaled down to fit risk budget" in final_decision["reason"]
    assert final_decision["position_size"] == 40
    # The entire remaining budget should be consumed.
    assert final_decision["risk_amount"] == 2000
    assert manager.remaining_budget == 0
    assert manager.approved_buys_value == (40 * 200) # 8000

def test_evaluate_buy_scaled_down_and_rejected_by_min_value(manager: PortfolioRiskManager):
    """Test scaling down that results in a value below the minimum."""
    # Similar to above, but the scaled value is too small.
    # Required risk is 4000, budget is 2000. Scaling factor = 0.5.
    # Original size 10, scaled size 5.
    # Entry price is 80. Scaled value is 5 * 80 = 400.
    # Min position value is 500, so it should be rejected.
    buy_decision = {
        "approved": True,
        "risk_amount": 4000,
        "position_size": 10,
        "entry_price": 80,
    }
    final_decision = manager.evaluate_buy(buy_decision)

    assert not final_decision["approved"]
    assert "is below minimum" in final_decision["reason"]
    # State should not change
    assert manager.remaining_budget == 2000
    assert manager.approved_buys_value == 0

def test_evaluate_unapproved_buy(manager: PortfolioRiskManager):
    """Test that a pre-rejected buy decision is passed through without changes."""
    buy_decision = {
        "approved": False,
        "reason": "Some upstream reason."
    }
    final_decision = manager.evaluate_buy(buy_decision)
    assert final_decision == buy_decision
    assert manager.remaining_budget == 2000
    assert manager.approved_buys_value == 0

import pytest
from unittest.mock import AsyncMock, patch
import os
import datetime

# Patch os.makedirs before importing the app to prevent PermissionError.
with patch('os.makedirs', return_value=None):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models import (
        CanonicalAgentResponse, CanonicalAgentData,
        AccountBalance, Position, CreateOrderResponse, Order
    )
    from app import risk_manager

client = TestClient(app)

# --- Mocks ---

def mock_canonical_response(ticker, action="buy", score=0.8, price=100.0):
    """Helper to create a canonical agent response."""
    return CanonicalAgentResponse(
        agent_type="technical",
        version="1.0",
        data=CanonicalAgentData(
            action=action,
            confidence_score=score,
            current_price=price,
            indicators={"stop_loss": price * 0.95}
        )
    )

@pytest.fixture
def mock_dependencies():
    """Mocks all external dependencies for the /analyze-multi endpoint."""
    with patch('app.main.call_agents', new_callable=AsyncMock) as mock_call_agents, \
         patch('app.main.DatabaseAgentClient', autospec=True) as mock_db_client_class, \
         patch('app.main.normalize_response') as mock_normalize, \
         patch('app.main.LearningAgentClient', autospec=True) as mock_learning_client:

        mock_call_agents.side_effect = lambda ticker: (
            ({"agent": "tech", "ticker": ticker}, {"agent": "fund", "ticker": ticker})
        )

        def normalize_side_effect(raw_data):
            ticker = raw_data.get("ticker")
            agent = raw_data.get("agent")
            actions = {"AAPL": "buy", "GOOG": "sell", "MSFT": "buy"}
            prices = {"AAPL": 150.0, "GOOG": 120.0, "MSFT": 300.0}
            scores = {"tech": {"AAPL": 0.9, "GOOG": 0.7, "MSFT": 0.8},
                      "fund": {"AAPL": 0.6, "GOOG": 0.8, "MSFT": 0.7}}
            if ticker in actions:
                return mock_canonical_response(ticker, actions[ticker], scores[agent][ticker], prices[ticker])
            return None
        mock_normalize.side_effect = normalize_side_effect

        mock_db_instance = mock_db_client_class.return_value.__aenter__.return_value
        mock_db_instance.get_account_balance.return_value = AccountBalance(cash_balance=100000.0)
        mock_db_instance.get_positions.return_value = [Position(symbol="GOOG", quantity=50, average_cost=90.0, current_market_price=120.0)]

        async def create_order_side_effect(account_id, order_body, correlation_id):
            return CreateOrderResponse(status="pending", order_id=hash(order_body.symbol))
        mock_db_instance.create_order.side_effect = create_order_side_effect

        async def execute_order_side_effect(order_id, correlation_id):
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            if order_id == hash("AAPL"): return Order(order_id=order_id, symbol="AAPL", status="executed", order_type="BUY", quantity=66, price=150.0, account_id=1, timestamp=now)
            if order_id == hash("GOOG"): return Order(order_id=order_id, symbol="GOOG", status="executed", order_type="SELL", quantity=50, price=120.0, account_id=1, timestamp=now)
            if order_id == hash("MSFT"): return Order(order_id=order_id, symbol="MSFT", status="executed", order_type="BUY", quantity=33, price=300.0, account_id=1, timestamp=now)
        mock_db_instance.execute_order.side_effect = execute_order_side_effect

        mock_learning_instance = mock_learning_client.return_value
        mock_learning_instance.trigger_learning_cycle.return_value = None

        yield { "learning_client": mock_learning_instance }

# --- Tests ---

@patch('app.main.config_manager')
@patch('app.synthesis.config_manager')
def test_analyze_multi_endpoint_success(mock_synthesis_cm, mock_main_cm, mock_dependencies):
    def config_side_effect(key, default=None):
        return {
            'AGENT_WEIGHTS': {"technical": 0.5, "fundamental": 0.5},
            'PER_REQUEST_RISK_BUDGET': 0.10, 'RISK_PER_TRADE': 0.01,
            'STOP_LOSS_PERCENTAGE': 0.10, 'MAX_POSITION_PERCENTAGE': 0.2,
            'ENABLE_TECHNICAL_STOP': True, 'MIN_POSITION_VALUE': 500,
            'MAX_TOTAL_EXPOSURE': 0.8
        }.get(key, default)
    mock_main_cm.get.side_effect = config_side_effect
    mock_synthesis_cm.get.side_effect = config_side_effect

    response = client.post("/analyze-multi", json={"tickers": ["AAPL", "GOOG", "MSFT"]})
    assert response.status_code == 200
    data = response.json()

    assert data["execution_summary"]["total_trades_approved"] == 3
    assert data["execution_summary"]["total_trades_executed"] == 3

    mock_dependencies["learning_client"].trigger_learning_cycle.assert_called_once()
    assert mock_dependencies["learning_client"].trigger_learning_cycle.call_args.kwargs['symbol'] == "MSFT"

@patch('app.main.config_manager')
@patch('app.synthesis.config_manager')
def test_position_scaling_on_risk_budget(mock_synthesis_cm, mock_main_cm, mock_dependencies):
    def config_side_effect(key, default=None):
        from app import config as static_config
        if key == 'PER_REQUEST_RISK_BUDGET': return 0.015 # Enough for AAPL, but MSFT will be scaled
        if key == 'AGENT_WEIGHTS': return {"technical": 0.5, "fundamental": 0.5}
        return getattr(static_config, key, default)
    mock_main_cm.get.side_effect = config_side_effect
    mock_synthesis_cm.get.side_effect = config_side_effect

    response = client.post("/analyze-multi", json={"tickers": ["AAPL", "MSFT"]})
    assert response.status_code == 200
    data = response.json()

    assert data["execution_summary"]["total_trades_approved"] == 2

    msft_result = next(r for r in data["results"] if r["ticker"] == "MSFT")
    assert "Position scaled down" in msft_result["execution_details"]["reason"]

@patch('app.main.config_manager')
@patch('app.synthesis.config_manager')
def test_max_exposure_limit(mock_synthesis_cm, mock_main_cm, mock_dependencies):
    def config_side_effect(key, default=None):
        from app import config as static_config
        if key == 'MAX_TOTAL_EXPOSURE': return 0.1 # Very low, will reject AAPL
        if key == 'AGENT_WEIGHTS': return {"technical": 0.5, "fundamental": 0.5}
        return getattr(static_config, key, default)
    mock_main_cm.get.side_effect = config_side_effect
    mock_synthesis_cm.get.side_effect = config_side_effect

    response = client.post("/analyze-multi", json={"tickers": ["AAPL", "MSFT"]})
    assert response.status_code == 200
    data = response.json()

    assert data["execution_summary"]["total_trades_approved"] == 1 # Only MSFT is approved

    aapl_result = next(r for r in data["results"] if r["ticker"] == "AAPL")
    assert "exceeds max total portfolio exposure" in aapl_result["execution_details"]["reason"]

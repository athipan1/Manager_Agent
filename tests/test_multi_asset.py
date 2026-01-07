import pytest
from unittest.mock import AsyncMock, patch
import os
import datetime
from decimal import Decimal

# Patch os.makedirs before importing the app to prevent PermissionError.
with patch('os.makedirs', return_value=None):
    from fastapi.testclient import TestClient
    from app.main import app
    from app.models import (
        AccountBalance, Position, CreateOrderResponse, Order, ReportDetails, ReportDetail,
        CanonicalAgentResponse, CanonicalAgentData
    )

client = TestClient(app)

# --- Mocks ---

def mock_analysis_result(ticker, final_verdict, tech_score=0.8, fund_score=0.7, price=Decimal("100.0")):
    """Helper to create a mock analysis result, simulating the output of _analyze_single_asset."""
    return {
        "ticker": ticker,
        "final_verdict": final_verdict,
        "status": "complete",
        "details": ReportDetails(
            technical=ReportDetail(action=final_verdict, score=tech_score, reason=""),
            fundamental=ReportDetail(action=final_verdict, score=fund_score, reason="")
        ),
        "raw_data": {
            "technical": CanonicalAgentResponse(agent_type="tech", version="1.0", data=CanonicalAgentData(action=final_verdict, confidence_score=tech_score, current_price=price, indicators={'stop_loss': price * Decimal("0.9")})),
            "fundamental": CanonicalAgentResponse(agent_type="fund", version="1.0", data=CanonicalAgentData(action=final_verdict, confidence_score=fund_score, current_price=price))
        }
    }

@pytest.fixture
def mock_high_level_dependencies():
    """Mocks dependencies by patching _analyze_single_asset directly."""
    with patch('app.main._analyze_single_asset', new_callable=AsyncMock) as mock_analyze, \
         patch('app.main.DatabaseAgentClient', autospec=True) as mock_db_client_class, \
         patch('app.main.LearningAgentClient', autospec=True) as mock_learning_client:

        # Let the test define the side effect for analysis
        mock_db_instance = mock_db_client_class.return_value.__aenter__.return_value
        mock_db_instance.get_account_balance.return_value = AccountBalance(cash_balance=Decimal("100000.0"))
        mock_db_instance.get_positions.return_value = [Position(symbol="GOOG", quantity=50, average_cost=Decimal("90.0"), current_market_price=Decimal("120.0"))]

        async def create_order_side_effect(account_id, order_body, correlation_id):
            return CreateOrderResponse(status="pending", order_id=hash(order_body.symbol))
        mock_db_instance.create_order.side_effect = create_order_side_effect

        async def execute_order_side_effect(order_id, correlation_id):
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            if order_id == hash("AAPL"): return Order(order_id=order_id, symbol="AAPL", status="executed", order_type="BUY", quantity=66, price=Decimal("150.0"), account_id=1, timestamp=now)
            if order_id == hash("GOOG"): return Order(order_id=order_id, symbol="GOOG", status="executed", order_type="SELL", quantity=50, price=Decimal("120.0"), account_id=1, timestamp=now)
            if order_id == hash("MSFT"): return Order(order_id=order_id, symbol="MSFT", status="executed", order_type="BUY", quantity=33, price=Decimal("300.0"), account_id=1, timestamp=now)
        mock_db_instance.execute_order.side_effect = execute_order_side_effect

        mock_learning_instance = mock_learning_client.return_value
        mock_learning_instance.trigger_learning_cycle.return_value = None

        yield { "analyze": mock_analyze, "learning": mock_learning_instance }

# --- Tests ---

@patch('app.main.config_manager')
def test_analyze_multi_endpoint_success(mock_main_cm, mock_high_level_dependencies):
    mock_main_cm.get.side_effect = lambda key, default=None: {
        'PER_REQUEST_RISK_BUDGET': '0.25', 'RISK_PER_TRADE': '0.01',
        'STOP_LOSS_PERCENTAGE': '0.10', 'MAX_POSITION_PERCENTAGE': '0.2',
        'ENABLE_TECHNICAL_STOP': True, 'MIN_POSITION_VALUE': '500',
        'MAX_TOTAL_EXPOSURE': '0.8'
    }.get(key, default)

    mock_high_level_dependencies["analyze"].side_effect = [
        mock_analysis_result("AAPL", "buy", tech_score=0.9, price=Decimal("150.0")),
        mock_analysis_result("GOOG", "sell", tech_score=0.8, price=Decimal("120.0")),
        mock_analysis_result("MSFT", "buy", tech_score=0.85, price=Decimal("300.0")),
    ]

    response = client.post("/analyze-multi", json={"tickers": ["AAPL", "GOOG", "MSFT"]})
    assert response.status_code == 200
    data = response.json()

    assert data["execution_summary"]["total_trades_approved"] == 3
    assert data["execution_summary"]["total_trades_executed"] == 3

    mock_high_level_dependencies["learning"].trigger_learning_cycle.assert_called_once()
    assert mock_high_level_dependencies["learning"].trigger_learning_cycle.call_args.kwargs['symbol'] == "AAPL"

@patch('app.main.config_manager')
def test_position_scaling_on_risk_budget(mock_main_cm, mock_high_level_dependencies):
    mock_main_cm.get.side_effect = lambda key, default=None: {
        'PER_REQUEST_RISK_BUDGET': '0.015', 'RISK_PER_TRADE': '0.01',
        'STOP_LOSS_PERCENTAGE': '0.10', 'MAX_POSITION_PERCENTAGE': '0.2',
        'ENABLE_TECHNICAL_STOP': True, 'MIN_POSITION_VALUE': '500',
        'MAX_TOTAL_EXPOSURE': '0.8'
    }.get(key, default)

    mock_high_level_dependencies["analyze"].side_effect = [
        mock_analysis_result("AAPL", "buy", tech_score=0.9, price=Decimal("150.0")),
        mock_analysis_result("MSFT", "buy", tech_score=0.8, price=Decimal("300.0")),
    ]

    response = client.post("/analyze-multi", json={"tickers": ["AAPL", "MSFT"]})
    assert response.status_code == 200
    data = response.json()

    assert data["execution_summary"]["total_trades_approved"] == 2

    msft_result = next(r for r in data["results"] if r['analysis']['ticker'] == "MSFT")
    assert "Position scaled down" in msft_result["execution"]["reason"]

@patch('app.main.config_manager')
def test_max_exposure_limit(mock_main_cm, mock_high_level_dependencies):
    mock_main_cm.get.side_effect = lambda key, default=None: {
        'MAX_TOTAL_EXPOSURE': '0.2', 'RISK_PER_TRADE': '0.01', # Increased to 0.2
        'STOP_LOSS_PERCENTAGE': '0.10', 'MAX_POSITION_PERCENTAGE': '0.2',
        'ENABLE_TECHNICAL_STOP': True, 'MIN_POSITION_VALUE': '500'
    }.get(key, default)

    mock_high_level_dependencies["analyze"].side_effect = [
        mock_analysis_result("AAPL", "buy", tech_score=0.9, price=Decimal("150.0")),
        mock_analysis_result("MSFT", "buy", tech_score=0.8, price=Decimal("300.0")),
    ]

    response = client.post("/analyze-multi", json={"tickers": ["AAPL", "MSFT"]})
    assert response.status_code == 200
    data = response.json()

    assert data["execution_summary"]["total_trades_approved"] == 1

    msft_result = next(r for r in data["results"] if r['analysis']['ticker'] == "MSFT")
    assert "exceeds max total portfolio exposure" in msft_result["execution"]["reason"]

import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
import datetime
from decimal import Decimal

# Patch os.makedirs before importing the app to prevent PermissionError.
with patch('os.makedirs', return_value=None):
    from app.main import app
    from app.models import (
        AccountBalance, Position, ReportDetails, ReportDetail
    )
    from app.contracts import StandardAgentResponse, StandardAgentData

client = TestClient(app)

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
            "technical": StandardAgentResponse(
                status="success",
                agent_type="technical",
                version="1.0",
                timestamp=datetime.datetime.now(),
                data=StandardAgentData(
                    action=final_verdict,
                    confidence_score=tech_score,
                    current_price=float(price),
                    indicators={'stop_loss': float(price * Decimal("0.9"))}
                )
            ),
            "fundamental": StandardAgentResponse(
                status="success",
                agent_type="fundamental",
                version="1.0",
                timestamp=datetime.datetime.now(),
                data=StandardAgentData(
                    action=final_verdict,
                    confidence_score=fund_score,
                    current_price=float(price)
                )
            )
        }
    }

@patch('app.main.ScannerAgentClient', autospec=True)
@patch('app.main._analyze_single_asset', new_callable=AsyncMock)
@patch('app.main._execute_trade', new_callable=AsyncMock)
@patch('app.main.DatabaseAgentClient', autospec=True)
@patch('app.main.LearningAgentClient', autospec=True)
@patch('app.main.config_manager')
def test_scan_and_analyze_technical_success(mock_cm, mock_learning, mock_db, mock_execute, mock_analyze, mock_scanner):
    # Setup config
    mock_cm.get.side_effect = lambda key, default=None: {
        'PER_REQUEST_RISK_BUDGET': '0.25', 'RISK_PER_TRADE': '0.01',
        'STOP_LOSS_PERCENTAGE': '0.10', 'MAX_POSITION_PERCENTAGE': '0.2',
        'ENABLE_TECHNICAL_STOP': True, 'MIN_POSITION_VALUE': '500',
        'MAX_TOTAL_EXPOSURE': '0.8',
        'DEFAULT_ACCOUNT_ID': 1
    }.get(key, default)

    # Mock Scanner
    mock_scanner_instance = mock_scanner.return_value.__aenter__.return_value
    mock_scanner_instance.scan.return_value = StandardAgentResponse(
        status="success",
        agent_type="Scanner_Agent",
        version="1.0.0",
        timestamp=datetime.datetime.now(),
        data={
            "candidates": [
                {"symbol": "AAPL", "recommendation": "STRONG_BUY"},
                {"symbol": "MSFT", "recommendation": "BUY"}
            ]
        }
    )

    # Mock Database
    mock_db_instance = mock_db.return_value.__aenter__.return_value
    mock_db_instance.get_account_balance.return_value = AccountBalance(cash_balance=Decimal("100000.0"))
    mock_db_instance.get_positions.return_value = []

    # Mock Analysis
    mock_analyze.return_value = mock_analysis_result("AAPL", "buy")

    # Mock Execution
    mock_execute.return_value = {"status": "submitted", "order_id": "mock-order", "details": {}}

    response = client.post("/scan-and-analyze", json={
        "scan_type": "technical",
        "max_candidates": 1
    })

    assert response.status_code == 200
    data = response.json()["data"]
    from unittest.mock import ANY
    assert data["results"][0]["analysis"]["ticker"] == "AAPL"
    mock_scanner_instance.scan.assert_called_once()
    mock_analyze.assert_called_once_with("AAPL", ANY)

@patch('app.main.ScannerAgentClient', autospec=True)
@patch('app.main.config_manager')
def test_scan_and_analyze_no_candidates(mock_cm, mock_scanner):
    # Setup config
    mock_cm.get.side_effect = lambda key, default=None: {'DEFAULT_ACCOUNT_ID': 1}.get(key, default)

    # Mock Scanner
    mock_scanner_instance = mock_scanner.return_value.__aenter__.return_value
    mock_scanner_instance.scan.return_value = StandardAgentResponse(
        status="success",
        agent_type="Scanner_Agent",
        version="1.0.0",
        timestamp=datetime.datetime.now(),
        data={"candidates": []}
    )

    response = client.post("/scan-and-analyze", json={
        "scan_type": "technical",
        "max_candidates": 5
    })

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["results"] == []
    assert data["execution_summary"]["total_trades_approved"] == 0

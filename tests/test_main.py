import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock

from app.main import app

client = TestClient(app)

# --- Mock data for agent responses ---
mock_tech_success = {
    "agent_type": "technical",
    "ticker": "AAPL",
    "status": "success",
    "data": {
        "current_price": 150.50,
        "action": "buy",
        "confidence_score": 0.85,
        "indicators": {"rsi": 35.5}
    }
}

mock_fund_success = {
    "agent_type": "fundamental",
    "ticker": "AAPL",
    "status": "success",
    "data": {
        "action": "hold",
        "confidence_score": 0.60,
        "analysis_summary": "Solid company.",
        "metrics": {"pe_ratio": 28.5}
    }
}

@patch('app.main.call_agents', new_callable=AsyncMock)
def test_analyze_ticker_success(mock_call_agents):
    """
    Tests the /analyze endpoint with successful agent responses.
    """
    # Mock the return value of call_agents
    mock_call_agents.return_value = (mock_tech_success, mock_fund_success)

    # Make the request
    response = client.post("/analyze", json={"ticker": "AAPL"})

    # Assertions
    assert response.status_code == 200
    data = response.json()
    assert data["ticker"] == "AAPL"
    assert data["final_verdict"] == "Buy"
    assert data["details"]["technical"]["action"] == "buy"
    assert data["details"]["fundamental"]["action"] == "hold"

@patch('app.main.call_agents', new_callable=AsyncMock)
def test_analyze_ticker_agent_error(mock_call_agents):
    """
    Tests the /analyze endpoint when one of the agents returns an error.
    """
    # Mock an error response from the technical agent
    mock_call_agents.return_value = ({"error": "Service Unavailable"}, mock_fund_success)

    # Make the request
    response = client.post("/analyze", json={"ticker": "AAPL"})

    # Assertions
    assert response.status_code == 500
    assert "Technical Agent Error" in response.json()["detail"]

def test_analyze_ticker_invalid_body():
    """
    Tests the /analyze endpoint with an invalid request body.
    """
    # Make a request with a missing 'ticker' field
    response = client.post("/analyze", json={"company": "AAPL"})

    # Assertions
    assert response.status_code == 422 # Unprocessable Entity

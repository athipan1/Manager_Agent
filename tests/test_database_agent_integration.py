import pytest
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

@pytest.fixture
def mock_call_agents():
    with patch('app.main.call_agents', new_callable=AsyncMock) as mock:
        yield mock

def test_analyze_ticker_all_agents_succeed(mock_call_agents):
    # Arrange
    mock_call_agents.return_value = (
        {
            "agent_type": "technical", "ticker": "AAPL", "status": "success",
            "data": {"current_price": 150.0, "action": "buy", "confidence_score": 0.8, "indicators": {}}
        },
        {
            "agent_type": "fundamental", "ticker": "AAPL", "status": "success",
            "data": {"action": "buy", "confidence_score": 0.9, "analysis_summary": "Strong buy", "metrics": {}}
        },
        {
            "ticker": "AAPL",
            "data": {"historical_data": {"2023-01-01": {"Open": 130.0}}}
        }
    )

    # Act
    response = client.post("/analyze", json={"ticker": "AAPL"})

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data['ticker'] == 'AAPL'
    assert data['final_verdict'] == 'Strong Buy'
    assert data['status'] == 'complete'
    assert data['details']['technical']['action'] == 'buy'
    assert data['details']['fundamental']['action'] == 'buy'
    assert data['historical_data'] is not None
    assert data['historical_data']['2023-01-01']['Open'] == 130.0

def test_analyze_ticker_database_agent_fails(mock_call_agents):
    # Arrange
    mock_call_agents.return_value = (
        {
            "agent_type": "technical", "ticker": "AAPL", "status": "success",
            "data": {"current_price": 150.0, "action": "buy", "confidence_score": 0.8, "indicators": {}}
        },
        {
            "agent_type": "fundamental", "ticker": "AAPL", "status": "success",
            "data": {"action": "buy", "confidence_score": 0.9, "analysis_summary": "Strong buy", "metrics": {}}
        },
        {"error": "Database agent failed"}
    )

    # Act
    response = client.post("/analyze", json={"ticker": "AAPL"})

    # Assert
    assert response.status_code == 200
    data = response.json()
    assert data['ticker'] == 'AAPL'
    assert data['final_verdict'] == 'Strong Buy'
    assert data['status'] == 'complete'
    assert data['historical_data'] is None

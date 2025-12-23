from fastapi.testclient import TestClient
from unittest.mock import patch
import pytest
import datetime

# Make the app module discoverable by pytest
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.main import app
from app.agent_client import call_agents
from app.models import AccountBalance, CreateOrderResponse, Order

client = TestClient(app)

# --- Mock Data ---
SUCCESS_TECH_RESPONSE = {
    "agent_type": "technical", "ticker": "GOOGL", "status": "success",
    "data": {"current_price": 2800.0, "action": "buy", "confidence_score": 0.85, "indicators": {}}
}
SUCCESS_FUND_RESPONSE = {
    "agent_type": "fundamental", "ticker": "GOOGL", "status": "success",
    "data": {"action": "buy", "confidence_score": 0.9, "analysis_summary": "", "metrics": {}}
}
ERROR_RESPONSE = {"error": "Agent failed"}


@pytest.fixture(autouse=True)
def mock_db_client():
    """Fixture to mock the DatabaseAgentClient for all tests in this module."""
    with patch("app.main.DatabaseAgentClient") as mock:
        instance = mock.return_value.__aenter__.return_value
        instance.get_account_balance.return_value = AccountBalance(cash_balance=10000.0)
        instance.get_positions.return_value = []
        instance.create_order.return_value = CreateOrderResponse(
            order_id=123, status="pending", symbol="GOOGL", quantity=10, price=2800.0
        )
        instance.execute_order.return_value = Order(
            order_id=123,
            account_id=1,
            symbol="GOOGL",
            order_type="BUY",
            quantity=10,
            price=2800.0,
            status="executed",
            timestamp=datetime.datetime.now(datetime.UTC).isoformat(),
        )
        yield mock


# --- Test Cases ---

def test_analyze_ticker_both_agents_succeed(monkeypatch):
    """Test when both agents return successful responses."""

    async def mock_call_agent(client, url, request_body):
        if "8000" in url: # Default port for Technical Agent
            return SUCCESS_TECH_RESPONSE
        elif "8001" in url: # Default port for Fundamental Agent
            return SUCCESS_FUND_RESPONSE
        raise ValueError(f"Unexpected URL in mock: {url}")

    monkeypatch.setattr("app.agent_client._call_agent", mock_call_agent)

    response = client.post("/analyze", json={"ticker": "GOOGL"})

    assert response.status_code == 200
    data = response.json()
    assert data["ticker"] == "GOOGL"
    assert data["status"] == "complete"
    assert data["final_verdict"] is not None
    assert data["details"]["technical"] is not None
    assert data["details"]["fundamental"] is not None
    assert data["details"]["technical"]["action"] == "buy"
    assert data["details"]["fundamental"]["action"] == "buy"

def test_analyze_ticker_technical_agent_fails(monkeypatch):
    """Test when only the technical agent fails."""

    async def mock_call_agent(client, url, request_body):
        if "8000" in url:
            return ERROR_RESPONSE
        elif "8001" in url:
            return SUCCESS_FUND_RESPONSE
        raise ValueError(f"Unexpected URL in mock: {url}")

    monkeypatch.setattr("app.agent_client._call_agent", mock_call_agent)

    response = client.post("/analyze", json={"ticker": "GOOGL"})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "partial"
    assert data["details"]["technical"] is None
    assert data["details"]["fundamental"] is not None
    assert data["details"]["fundamental"]["action"] == "buy"

def test_analyze_ticker_fundamental_agent_fails(monkeypatch):
    """Test when only the fundamental agent fails."""

    async def mock_call_agent(client, url, request_body):
        if "8000" in url:
            return SUCCESS_TECH_RESPONSE
        elif "8001" in url:
            return ERROR_RESPONSE
        raise ValueError(f"Unexpected URL in mock: {url}")

    monkeypatch.setattr("app.agent_client._call_agent", mock_call_agent)

    response = client.post("/analyze", json={"ticker": "GOOGL"})

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "partial"
    assert data["details"]["technical"] is not None
    assert data["details"]["fundamental"] is None
    assert data["details"]["technical"]["action"] == "buy"

def test_analyze_ticker_both_agents_fail(monkeypatch):
    """Test when both agents fail."""

    async def mock_call_agent(client, url, request_body):
        return ERROR_RESPONSE

    monkeypatch.setattr("app.agent_client._call_agent", mock_call_agent)

    response = client.post("/analyze", json={"ticker": "GOOGL"})

    assert response.status_code == 500
    assert "Both Technical and Fundamental Agents failed to provide valid responses" in response.json()["detail"]

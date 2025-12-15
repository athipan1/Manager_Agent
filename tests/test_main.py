from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
import pytest

# Make the app module discoverable by pytest
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.main import app
from app.agent_client import call_agents

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
    assert "Both Technical and Fundamental Agents failed to respond" in response.json()["detail"]

from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
import pytest
from app.main import app
import datetime

client = TestClient(app)

@pytest.mark.asyncio
@patch("app.main.DatabaseAgentClient")
@patch("app.main.call_agents")
@patch("app.main.LearningAgentClient")
async def test_analyze_endpoint_standard_response(mock_learning_client, mock_call_agents, mock_db_client):
    # Mock DB Client
    mock_db_instance = mock_db_client.return_value.__aenter__.return_value
    mock_db_instance.get_account_balance = AsyncMock(return_value=AsyncMock(cash_balance=10000))
    mock_db_instance.get_positions = AsyncMock(return_value=[])

    # Mock call_agents
    from app.contracts import StandardAgentResponse, StandardAgentData
    tech_data = StandardAgentData(action="buy", confidence_score=0.8, reason="Technical buy")
    fund_data = StandardAgentData(action="buy", confidence_score=0.7, reason="Fundamental buy")

    tech_resp = StandardAgentResponse(
        status="success", agent_type="technical", version="1.0",
        timestamp=datetime.datetime.now(datetime.UTC), data=tech_data
    )
    fund_resp = StandardAgentResponse(
        status="success", agent_type="fundamental", version="1.0",
        timestamp=datetime.datetime.now(datetime.UTC), data=fund_data
    )
    mock_call_agents.return_value = (tech_resp, fund_resp)

    # Mock LearningAgentClient
    mock_learning_instance = mock_learning_client.return_value
    mock_learning_instance.trigger_learning_cycle = AsyncMock(return_value=None)

    # Call endpoint
    response = client.post("/analyze", json={"ticker": "AAPL", "account_id": 1})

    assert response.status_code == 200
    json_response = response.json()
    assert json_response["status"] == "success"
    assert json_response["agent_type"] == "manager-agent"
    assert "data" in json_response
    assert json_response["data"]["ticker"] == "AAPL"
    assert "final_verdict" in json_response["data"]

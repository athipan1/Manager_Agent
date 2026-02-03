from fastapi.testclient import TestClient
from unittest.mock import patch, AsyncMock
import pytest
from app.main import app

client = TestClient(app)

# ==================================
# Health Check Endpoint Tests
# ==================================

def test_health_check_success():
    """
    Test the /health endpoint when all dependencies are healthy.
    It should return 200 OK and StandardAgentResponse.
    """
    with patch("app.main.DatabaseAgentClient") as mock_db_client:
        mock_instance = mock_db_client.return_value.__aenter__.return_value
        mock_instance.health = AsyncMock()

        response = client.get("/health")

        assert response.status_code == 200
        json_response = response.json()
        assert json_response["status"] == "success"
        assert json_response["agent_type"] == "manager-agent"
        assert "timestamp" in json_response
        assert json_response["data"]["dependencies"]["database_agent"]["status"] == "healthy"

def test_health_check_dependency_failure():
    """
    Test the /health endpoint when a critical dependency (Database Agent) is unhealthy.
    It should return 503 Service Unavailable and StandardAgentResponse with status error.
    """
    with patch("app.main.DatabaseAgentClient") as mock_db_client:
        mock_db_client.return_value.__aenter__.side_effect = ConnectionError("Failed to connect to DB")

        response = client.get("/health")

        assert response.status_code == 503
        json_response = response.json()
        assert json_response["status"] == "error"
        assert json_response["agent_type"] == "manager-agent"
        assert json_response["data"]["dependencies"]["database_agent"]["status"] == "unhealthy"
        assert "Connection failed" in json_response["data"]["dependencies"]["database_agent"]["details"]

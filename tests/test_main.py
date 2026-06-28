from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from app.main_modular import app

client = TestClient(app)

# ==================================
# Health Check Endpoint Tests
# ==================================


def test_health_check_success():
    """
    Test the /health endpoint when all dependencies are healthy.
    It should return 200 OK and StandardAgentResponse.
    """
    with patch("app.routes.system.DatabaseAgentClient") as mock_db_client, patch(
        "app.routes.system.check_risk_agent_health_async", new_callable=AsyncMock
    ) as mock_risk_health:
        mock_instance = mock_db_client.return_value.__aenter__.return_value
        mock_instance.health = AsyncMock()
        mock_risk_health.return_value = {"status": "healthy"}

        response = client.get("/health")

        assert response.status_code == 200
        json_response = response.json()
        assert json_response["status"] == "success"
        assert json_response["agent_type"] == "manager-agent"
        assert "timestamp" in json_response
        assert json_response["data"]["dependencies"]["database_agent"]["status"] == "healthy"
        assert json_response["data"]["dependencies"]["risk_agent"]["status"] == "healthy"


def test_health_check_dependency_failure():
    """
    Test the /health endpoint when a critical dependency (Database Agent) is unhealthy.
    It should return 503 Service Unavailable and StandardAgentResponse with status error.
    """
    with patch("app.routes.system.DatabaseAgentClient") as mock_db_client, patch(
        "app.routes.system.check_risk_agent_health_async", new_callable=AsyncMock
    ) as mock_risk_health:
        mock_db_client.return_value.__aenter__.side_effect = ConnectionError("Failed to connect to DB")
        mock_risk_health.return_value = {"status": "healthy"}

        response = client.get("/health")

        assert response.status_code == 503
        json_response = response.json()
        assert json_response["status"] == "error"
        assert json_response["agent_type"] == "manager-agent"
        assert json_response["data"]["dependencies"]["database_agent"]["status"] == "unhealthy"
        assert "Connection failed" in json_response["data"]["dependencies"]["database_agent"]["details"]
        assert json_response["data"]["dependencies"]["risk_agent"]["status"] == "healthy"


def test_health_check_risk_agent_failure():
    """
    Test the /health endpoint when Risk_Agent is unhealthy.
    It should fail closed and return 503.
    """
    with patch("app.routes.system.DatabaseAgentClient") as mock_db_client, patch(
        "app.routes.system.check_risk_agent_health_async", new_callable=AsyncMock
    ) as mock_risk_health:
        mock_instance = mock_db_client.return_value.__aenter__.return_value
        mock_instance.health = AsyncMock()
        mock_risk_health.side_effect = ConnectionError("Failed to connect to Risk_Agent")

        response = client.get("/health")

        assert response.status_code == 503
        json_response = response.json()
        assert json_response["status"] == "error"
        assert json_response["agent_type"] == "manager-agent"
        assert json_response["data"]["dependencies"]["database_agent"]["status"] == "healthy"
        assert json_response["data"]["dependencies"]["risk_agent"]["status"] == "unhealthy"
        assert "Connection failed" in json_response["data"]["dependencies"]["risk_agent"]["details"]

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
    It should return 200 OK.
    """
    # We use a context manager to patch the client for the duration of this test.
    with patch("app.main.DatabaseAgentClient") as mock_db_client:
        # Mock the async context manager (__aenter__) and its methods.
        mock_instance = mock_db_client.return_value.__aenter__.return_value
        mock_instance.get_account_balance = AsyncMock()

        # Make the request to the endpoint.
        response = client.get("/health")

        # Assert the response is as expected.
        assert response.status_code == 200
        json_response = response.json()
        assert json_response["status"] == "ok"
        assert json_response["dependencies"]["database_agent"]["status"] == "healthy"

def test_health_check_dependency_failure():
    """
    Test the /health endpoint when a critical dependency (Database Agent) is unhealthy.
    It should return 503 Service Unavailable.
    """
    # We patch the client to simulate a connection failure.
    with patch("app.main.DatabaseAgentClient") as mock_db_client:
        # Configure the async context manager to raise an exception.
        mock_db_client.return_value.__aenter__.side_effect = ConnectionError("Failed to connect to DB")

        # Make the request.
        response = client.get("/health")

        # Assert the response indicates the service is unavailable.
        assert response.status_code == 503
        json_response = response.json()
        assert json_response["status"] == "unhealthy"
        assert json_response["dependencies"]["database_agent"]["status"] == "unhealthy"
        assert "Connection failed" in json_response["dependencies"]["database_agent"]["details"]

# Placeholder for existing tests if they were to be added back.
# For this task, we are only focusing on the health check functionality.

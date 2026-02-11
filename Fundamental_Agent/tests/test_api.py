import sys
import os
from unittest.mock import patch
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


@patch('app.main.run_analysis')
def test_analyze_endpoint_success_growth(mock_run_analysis):
    """Test a successful analysis for the 'growth' style."""
    mock_run_analysis.return_value = {
        "strength": "buy",
        "score": 0.75,
        "reasoning": "Strong growth prospects."
    }
    response = client.post(
        "/analyze",
        json={"ticker": "AAPL", "style": "growth"},
        headers={"X-Correlation-ID": "test-growth-123"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["agent_type"] == "fundamental"
    assert data["version"] == "2.0.0"
    assert data["status"] == "success"
    assert data["error"] is None

    analysis_data = data["data"]
    assert analysis_data["action"] == "buy"
    assert analysis_data["confidence_score"] == 0.75
    assert analysis_data["reason"] == "Strong growth prospects."
    assert analysis_data["source"] == "fundamental_agent"

    mock_run_analysis.assert_called_with("AAPL", "growth", correlation_id="test-growth-123")


@patch('app.main.run_analysis')
def test_analyze_endpoint_success_value(mock_run_analysis):
    """Test a successful analysis for the 'value' style."""
    mock_run_analysis.return_value = {
        "strength": "neutral",
        "score": 0.5,
        "reasoning": "Fairly valued."
    }
    response = client.post("/analyze", json={"ticker": "MSFT", "style": "value"})
    assert response.status_code == 200
    data = response.json()
    assert data["agent_type"] == "fundamental"
    assert data["version"] == "2.0.0"
    assert data["status"] == "success"

    analysis_data = data["data"]
    assert analysis_data["action"] == "hold"
    assert analysis_data["confidence_score"] == 0.5
    assert analysis_data["source"] == "fundamental_agent"


@patch('app.main.run_analysis')
def test_analyze_endpoint_ticker_not_found(mock_run_analysis):
    """Test the response for a ticker that is not found."""
    mock_run_analysis.return_value = {"error": "ticker_not_found"}
    response = client.post("/analyze", json={"ticker": "INVALIDTICKER"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"

    error_data = data["data"]
    assert error_data["action"] == "hold"
    assert error_data["confidence_score"] == 0.0
    assert error_data["reason"] == "ticker_not_found"

    error = data["error"]
    assert error["code"] == "TICKER_NOT_FOUND"
    assert error["message"] == "ticker_not_found"
    assert not error["retryable"]


@patch('app.main.run_analysis')
def test_analyze_endpoint_insufficient_data(mock_run_analysis):
    """Test the response when there is not enough data for analysis."""
    mock_run_analysis.return_value = {"error": "data_not_enough"}
    response = client.post("/analyze", json={"ticker": "NODATA"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"

    error_data = data["data"]
    assert error_data["action"] == "hold"
    assert error_data["confidence_score"] == 0.0
    assert error_data["reason"] == "data_not_enough"

    error = data["error"]
    assert error["code"] == "INSUFFICIENT_DATA"
    assert error["message"] == "data_not_enough"


@patch('app.main.run_analysis')
def test_analyze_endpoint_model_error(mock_run_analysis):
    """Test the response when the analysis model fails."""
    mock_run_analysis.return_value = {"error": "some_model_error"}
    response = client.post("/analyze", json={"ticker": "FAILMODEL"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "error"

    error_data = data["data"]
    assert error_data["action"] == "hold"
    assert error_data["confidence_score"] == 0.0
    assert error_data["reason"] == "some_model_error"

    error = data["error"]
    assert error["code"] == "ANALYSIS_FAILED"
    assert error["message"] == "some_model_error"


def test_health_endpoint():
    """Test the health check endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["agent_type"] == "fundamental"
    assert data["data"]["status"] == "healthy"


def test_root_endpoint():
    """Test the root endpoint."""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["agent_type"] == "fundamental"
    assert data["data"]["message"] == "Hello World"

from fastapi.testclient import TestClient
from app.main import app
from datetime import datetime

client = TestClient(app)

def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    json_data = response.json()
    assert json_data["status"] == "success"
    assert json_data["agent_type"] == "scanner"
    assert json_data["version"] == "1.0.0"
    assert "timestamp" in json_data
    # Verify ISO-8601 format
    ts = json_data["timestamp"].replace("Z", "+00:00")
    datetime.fromisoformat(ts)
    assert json_data["data"] == {"message": "healthy"}
    assert "error" in json_data

def test_scan_fundamental_endpoint_no_symbols():
    response = client.post("/scan/fundamental", json={})
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["status"] in ["success", "error"]
    assert "agent_type" in response_json
    assert "version" in response_json
    assert "timestamp" in response_json
    assert "error" in response_json
    assert "data" in response_json
    data = response_json["data"]
    assert data["scan_type"] == "fundamental"
    assert "count" in data
    assert "candidates" in data
    assert isinstance(data["candidates"], list)
    assert data["count"] == len(data["candidates"])

def test_scan_fundamental_endpoint_with_symbols():
    response = client.post("/scan/fundamental", json={"symbols": ["AAPL", "GOOG"]})
    assert response.status_code == 200
    response_json = response.json()
    assert response_json["status"] in ["success", "error"]
    assert "version" in response_json
    assert "error" in response_json
    assert "data" in response_json
    data = response_json["data"]
    assert data["scan_type"] == "fundamental"
    assert "count" in data
    assert "candidates" in data
    assert data["count"] <= 2

def test_scan_endpoint():
    response = client.post("/scan", json={"symbols": ["AAPL", "MSFT"]})
    assert response.status_code == 200
    response_json = response.json()
    assert "agent_type" in response_json
    assert "status" in response_json
    assert "version" in response_json
    assert "error" in response_json
    assert "data" in response_json
    data = response_json["data"]
    assert data["scan_type"] == "technical"
    assert "count" in data
    assert "candidates" in data
    assert isinstance(data["candidates"], list)

import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.contracts import StandardAgentResponse
from app.routes.system import router


REQUIRED_STANDARD_RESPONSE_FIELDS = {
    "status",
    "agent_type",
    "version",
    "schema_version",
    "timestamp",
    "correlation_id",
    "data",
    "metadata",
    "error",
}


def make_app():
    app = FastAPI()
    app.include_router(router)
    return app


def assert_standard_response(payload):
    assert REQUIRED_STANDARD_RESPONSE_FIELDS.issubset(payload.keys())
    assert payload["schema_version"] == "1.0"
    assert payload["agent_type"] == "manager-agent"
    assert payload["correlation_id"]


def test_standard_response_contract_defaults_are_backward_compatible():
    response = StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=datetime.datetime.now(datetime.UTC),
        data={"message": "ok"},
    )

    payload = response.model_dump(mode="json")

    assert payload["schema_version"] == "1.0"
    assert "correlation_id" in payload
    assert payload["correlation_id"] is None


def test_standard_response_accepts_named_profit_contract_version():
    response = StandardAgentResponse(
        status="success",
        agent_type="profit-agent",
        version="0.2.0",
        schema_version="profit-decision.v2",
        timestamp="2026-07-22T00:00:00Z",
        correlation_id="profit-correlation-id",
        data={},
        metadata={},
        error=None,
        confidence_score=0.9,
    )

    assert response.schema_version == "profit-decision.v2"
    assert response.confidence_score == 0.9


def test_version_endpoint_uses_standard_response_contract():
    client = TestClient(make_app())
    response = client.get("/version")

    assert response.status_code == 200
    payload = response.json()
    assert_standard_response(payload)
    assert payload["data"]["api_contract"] == "multi-agent-trading-api-contract"
    assert payload["data"]["schema_version"] == "1.0"


def test_ready_endpoint_uses_standard_response_contract():
    client = TestClient(make_app())
    response = client.get("/ready")

    assert response.status_code == 200
    payload = response.json()
    assert_standard_response(payload)
    assert payload["data"]["ready"] is True
    assert "dependencies" in payload["data"]

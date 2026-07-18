import pytest

import app.alpha_agent_client as alpha_agent_client
from app.alpha_agent_client import (
    ALPHA_AGENT_SPECS,
    _call_alpha_agent,
    _health_alpha_agent,
    build_alpha_advisory,
)


@pytest.mark.asyncio
async def test_build_alpha_advisory_skips_all_when_disabled():
    result = await build_alpha_advisory({}, "test-correlation-id")
    assert result["advisory_only"] is True
    assert result["enabled"] is False
    assert result["results"] == {}
    assert result["errors"] == {}
    assert set(result["skipped"]) == {"market_regime", "portfolio", "profit", "performance"}


class _ValidatedResponse:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self, mode="json"):
        return self.payload


@pytest.mark.asyncio
async def test_portfolio_advisory_client_sets_api_key_and_correlation_id(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, *, base_url, timeout, headers=None):
            captured["base_url"] = base_url
            captured["timeout"] = timeout
            captured["headers"] = headers

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

        async def _post(self, endpoint, correlation_id, payload):
            captured["endpoint"] = endpoint
            captured["correlation_id"] = correlation_id
            captured["payload"] = payload
            return {"status": "success"}

        def validate_standard_response(self, response):
            return _ValidatedResponse(response)

    monkeypatch.setattr(alpha_agent_client, "ResilientAgentClient", FakeClient)
    payload = {"equity": 100_000, "cash": 100_000, "positions": []}
    await _call_alpha_agent(ALPHA_AGENT_SPECS["portfolio"], "portfolio-correlation", payload)

    assert captured["headers"] == {"X-API-KEY": "dev_portfolio_key"}
    assert captured["correlation_id"] == "portfolio-correlation"
    assert captured["endpoint"] == "/portfolio/exposure"
    assert captured["payload"] == payload


@pytest.mark.asyncio
async def test_portfolio_health_client_uses_same_api_key(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, *, base_url, timeout, headers=None):
            captured["headers"] = headers

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

        async def _get(self, endpoint, correlation_id):
            captured["endpoint"] = endpoint
            captured["correlation_id"] = correlation_id
            return {"status": "success"}

        def validate_standard_response(self, response):
            return _ValidatedResponse(response)

    monkeypatch.setattr(alpha_agent_client, "ResilientAgentClient", FakeClient)
    await _health_alpha_agent(ALPHA_AGENT_SPECS["portfolio"], "health-correlation")

    assert captured["headers"] == {"X-API-KEY": "dev_portfolio_key"}
    assert captured["endpoint"] == "/health"
    assert captured["correlation_id"] == "health-correlation"

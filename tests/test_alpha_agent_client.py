from dataclasses import replace

import pytest

import app.alpha_agent_client as alpha_agent_client
from app.alpha_agent_client import (
    ALPHA_AGENT_SPECS,
    _call_alpha_agent,
    _health_alpha_agent,
    build_alpha_advisory,
    recommend_market_strategy,
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
        self.data = payload.get("data") if isinstance(payload, dict) else None

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


@pytest.mark.asyncio
async def test_profit_advisory_client_sets_api_key_and_correlation_id(monkeypatch):
    captured = {}

    class FakeClient:
        def __init__(self, *, base_url, timeout, headers=None):
            captured["headers"] = headers

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

        async def _post(self, endpoint, correlation_id, payload):
            captured.update(
                endpoint=endpoint,
                correlation_id=correlation_id,
                payload=payload,
            )
            return {"status": "success"}

        def validate_standard_response(self, response):
            return _ValidatedResponse(response)

    monkeypatch.setattr(alpha_agent_client, "ResilientAgentClient", FakeClient)
    spec = replace(ALPHA_AGENT_SPECS["profit"], api_key="profit-service-key")
    await _call_alpha_agent(spec, "profit-correlation-id", {"position": {}})

    assert captured["headers"] == {"X-API-KEY": "profit-service-key"}
    assert captured["correlation_id"] == "profit-correlation-id"
    assert captured["endpoint"] == "/profit/plan"


@pytest.mark.asyncio
async def test_market_regime_advisory_client_sets_api_key_and_correlation_id(monkeypatch):
    captured = {}
    monkeypatch.setenv("MARKET_REGIME_AGENT_API_KEY", "market-service-key")

    class FakeClient:
        def __init__(self, *, base_url, timeout, headers=None):
            captured["headers"] = headers

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

        async def _post(self, endpoint, correlation_id, payload):
            captured.update(
                endpoint=endpoint,
                correlation_id=correlation_id,
                payload=payload,
            )
            return {
                "status": "success",
                "agent_type": "market-regime-agent",
                "schema_version": "1.1",
                "correlation_id": correlation_id,
                "data": payload,
            }

        def validate_standard_response(self, response):
            return _ValidatedResponse(response)

    monkeypatch.setattr(alpha_agent_client, "ResilientAgentClient", FakeClient)
    payload = {"symbol": "SPY"}
    await _call_alpha_agent(
        ALPHA_AGENT_SPECS["market_regime"],
        "market-correlation-id",
        payload,
    )

    assert captured["headers"] == {"X-API-KEY": "market-service-key"}
    assert captured["correlation_id"] == "market-correlation-id"
    assert captured["endpoint"] == "/market/regime"
    assert captured["payload"] == payload


@pytest.mark.asyncio
async def test_market_strategy_returns_fail_closed_gate_and_preserves_correlation(monkeypatch):
    captured = {}
    monkeypatch.setenv("MARKET_REGIME_AGENT_API_KEY", "market-service-key")

    class FakeClient:
        def __init__(self, *, base_url, timeout, headers=None):
            captured["headers"] = headers

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

        async def _post(self, endpoint, correlation_id, payload):
            captured.update(endpoint=endpoint, correlation_id=correlation_id)
            return {
                "status": "success",
                "agent_type": "market-regime-agent",
                "version": "0.2.0",
                "schema_version": "1.1",
                "timestamp": "2026-08-16T00:00:00Z",
                "correlation_id": correlation_id,
                "data": {
                    "recommended_action": "trade",
                    "recommended_strategy": "trend_following",
                    "position_size_multiplier": 1.0,
                    "risk_multiplier": 1.0,
                    "risk_budget_multiplier": 1.0,
                    "exposure_cap": 1.0,
                    "allowed_strategies": ["trend_following"],
                    "data_quality": {"status": "good", "trade_allowed": True},
                },
                "metadata": {},
                "error": None,
            }

        def validate_standard_response(self, response):
            return _ValidatedResponse(response)

    monkeypatch.setattr(alpha_agent_client, "ResilientAgentClient", FakeClient)

    result = await recommend_market_strategy({"symbol": "SPY"}, "market-correlation-id")

    assert captured["headers"] == {"X-API-KEY": "market-service-key"}
    assert captured["endpoint"] == "/market/strategy"
    assert captured["correlation_id"] == "market-correlation-id"
    assert result["gate"]["new_entries_allowed"] is True
    assert result["gate"]["decision"] == "PASS"

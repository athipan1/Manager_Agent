from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .config import (
    ALPHA_AGENTS_ENABLED,
    MARKET_REGIME_AGENT_ENABLED,
    MARKET_REGIME_AGENT_URL,
    MARKET_REGIME_AGENT_TIMEOUT,
    PERFORMANCE_AGENT_ENABLED,
    PERFORMANCE_AGENT_TIMEOUT,
    PERFORMANCE_AGENT_URL,
    PORTFOLIO_AGENT_API_KEY,
    PORTFOLIO_AGENT_ENABLED,
    PORTFOLIO_AGENT_TIMEOUT,
    PORTFOLIO_AGENT_URL,
    PROFIT_AGENT_ENABLED,
    PROFIT_AGENT_TIMEOUT,
    PROFIT_AGENT_URL,
)
from .resilient_client import ResilientAgentClient
from .services.serialization_service import dict_or_empty


@dataclass(frozen=True)
class AlphaAgentSpec:
    name: str
    base_url: str
    enabled: bool
    timeout: int
    advisory_endpoint: str
    payload_key: str
    api_key: Optional[str] = None


ALPHA_AGENT_SPECS = {
    "market_regime": AlphaAgentSpec(
        name="market_regime",
        base_url=MARKET_REGIME_AGENT_URL,
        enabled=MARKET_REGIME_AGENT_ENABLED,
        timeout=MARKET_REGIME_AGENT_TIMEOUT,
        advisory_endpoint="/market/regime",
        payload_key="market_regime",
    ),
    "portfolio": AlphaAgentSpec(
        name="portfolio",
        base_url=PORTFOLIO_AGENT_URL,
        enabled=PORTFOLIO_AGENT_ENABLED,
        timeout=PORTFOLIO_AGENT_TIMEOUT,
        advisory_endpoint="/portfolio/exposure",
        payload_key="portfolio",
        api_key=PORTFOLIO_AGENT_API_KEY,
    ),
    "profit": AlphaAgentSpec(
        name="profit",
        base_url=PROFIT_AGENT_URL,
        enabled=PROFIT_AGENT_ENABLED,
        timeout=PROFIT_AGENT_TIMEOUT,
        advisory_endpoint="/profit/plan",
        payload_key="profit",
    ),
    "performance": AlphaAgentSpec(
        name="performance",
        base_url=PERFORMANCE_AGENT_URL,
        enabled=PERFORMANCE_AGENT_ENABLED,
        timeout=PERFORMANCE_AGENT_TIMEOUT,
        advisory_endpoint="/performance/report",
        payload_key="performance",
    ),
}


def _client_headers(spec: AlphaAgentSpec) -> Dict[str, str] | None:
    if not spec.api_key:
        return None
    return {"X-API-KEY": spec.api_key}


def _client_for_spec(spec: AlphaAgentSpec) -> ResilientAgentClient:
    return ResilientAgentClient(
        base_url=spec.base_url,
        timeout=spec.timeout,
        headers=_client_headers(spec),
    )


async def _call_alpha_agent(
    spec: AlphaAgentSpec,
    correlation_id: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    async with _client_for_spec(spec) as client:
        response = await client._post(spec.advisory_endpoint, correlation_id, payload)
        validated = client.validate_standard_response(response)
        return validated.model_dump(mode="json")


async def _health_alpha_agent(spec: AlphaAgentSpec, correlation_id: str) -> Dict[str, Any]:
    async with _client_for_spec(spec) as client:
        response = await client._get("/health", correlation_id)
        validated = client.validate_standard_response(response)
        return validated.model_dump(mode="json")


async def recommend_market_strategy(
    request_payload: Dict[str, Any],
    correlation_id: str,
) -> Dict[str, Any]:
    """Ask Market_Regime_Agent for the strategy best suited to the current regime."""
    if not MARKET_REGIME_AGENT_ENABLED:
        return {
            "enabled": False,
            "skipped": "MARKET_REGIME_AGENT_ENABLED is false",
            "recommendation": None,
        }
    async with ResilientAgentClient(base_url=MARKET_REGIME_AGENT_URL, timeout=MARKET_REGIME_AGENT_TIMEOUT) as client:
        response = await client._post("/market/strategy", correlation_id, request_payload)
        validated = client.validate_standard_response(response)
        return {
            "enabled": True,
            "recommendation": dict_or_empty(validated.data),
        }


async def build_alpha_advisory(
    request_payload: Dict[str, Any],
    correlation_id: str,
) -> Dict[str, Any]:
    """Call enabled alpha/profit-management agents and aggregate advisory results.

    This helper is intentionally advisory-only. It must not call Execution_Agent.
    """
    results: Dict[str, Any] = {}
    skipped: Dict[str, str] = {}

    if not ALPHA_AGENTS_ENABLED:
        return {
            "advisory_only": True,
            "enabled": False,
            "results": results,
            "skipped": {name: "ALPHA_AGENTS_ENABLED is false" for name in ALPHA_AGENT_SPECS},
            "errors": {},
        }

    tasks: Dict[str, asyncio.Task] = {}
    for name, spec in ALPHA_AGENT_SPECS.items():
        if not spec.enabled:
            skipped[name] = f"{name} agent is disabled"
            continue
        payload = request_payload.get(spec.payload_key)
        if not payload:
            skipped[name] = f"missing payload key: {spec.payload_key}"
            continue
        tasks[name] = asyncio.create_task(_call_alpha_agent(spec, correlation_id, payload))

    task_results = await asyncio.gather(*tasks.values(), return_exceptions=True) if tasks else []
    errors: Dict[str, str] = {}
    for name, result in zip(tasks.keys(), task_results):
        if isinstance(result, BaseException):
            errors[name] = str(result)
        else:
            results[name] = result

    return {
        "advisory_only": True,
        "enabled": True,
        "results": results,
        "skipped": skipped,
        "errors": errors,
    }


async def check_alpha_health(correlation_id: str) -> Dict[str, Any]:
    if not ALPHA_AGENTS_ENABLED:
        return {
            "enabled": False,
            "services": {name: {"status": "disabled"} for name in ALPHA_AGENT_SPECS},
        }

    tasks: Dict[str, asyncio.Task] = {}
    services: Dict[str, Any] = {}
    for name, spec in ALPHA_AGENT_SPECS.items():
        if not spec.enabled:
            services[name] = {"status": "disabled"}
            continue
        tasks[name] = asyncio.create_task(_health_alpha_agent(spec, correlation_id))

    task_results = await asyncio.gather(*tasks.values(), return_exceptions=True) if tasks else []
    for name, result in zip(tasks.keys(), task_results):
        if isinstance(result, BaseException):
            services[name] = {"status": "unhealthy", "error": str(result)}
        else:
            services[name] = {"status": "healthy", "response": result}

    return {"enabled": True, "services": services}

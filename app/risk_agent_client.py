import asyncio
import os
import threading
import time
from typing import Any, Dict

import httpx


RISK_AGENT_URL = os.getenv("RISK_AGENT_URL", "http://risk-agent:8007")
RISK_AGENT_TIMEOUT = float(os.getenv("RISK_AGENT_TIMEOUT", "10"))
RISK_AGENT_FAILURE_THRESHOLD = int(os.getenv("RISK_AGENT_FAILURE_THRESHOLD", "3"))
RISK_AGENT_COOLDOWN_SECONDS = float(os.getenv("RISK_AGENT_COOLDOWN_SECONDS", "30"))

_failure_count = 0
_circuit_open_until = 0.0


class RiskAgentCircuitOpen(RuntimeError):
    """Raised when Risk Agent calls are temporarily blocked after repeated failures."""


def _circuit_is_open() -> bool:
    return time.monotonic() < _circuit_open_until


def _record_success() -> None:
    global _failure_count, _circuit_open_until
    _failure_count = 0
    _circuit_open_until = 0.0


def _record_failure() -> None:
    global _failure_count, _circuit_open_until
    _failure_count += 1
    if _failure_count >= RISK_AGENT_FAILURE_THRESHOLD:
        _circuit_open_until = time.monotonic() + RISK_AGENT_COOLDOWN_SECONDS


def _correlation_headers(correlation_id: str | None = None) -> Dict[str, str]:
    return {"X-Correlation-ID": correlation_id} if correlation_id else {}


async def check_risk_agent_health_async(correlation_id: str | None = None) -> Dict[str, Any]:
    """Return Risk_Agent health without applying StandardAgentResponse validation.

    Risk_Agent deliberately uses its own lightweight response shapes for risk
    checks, so Manager keeps this client tolerant and only requires that /health
    is reachable and reports a non-error status.
    """
    if _circuit_is_open():
        raise RiskAgentCircuitOpen("Risk_Agent circuit breaker is open; health is unavailable.")

    try:
        async with httpx.AsyncClient(base_url=RISK_AGENT_URL, timeout=RISK_AGENT_TIMEOUT) as client:
            response = await client.get("/health", headers=_correlation_headers(correlation_id))
            response.raise_for_status()
            result = response.json()
            _record_success()
            return result
    except Exception:
        _record_failure()
        raise


async def evaluate_risk_async(payload: Dict[str, Any], correlation_id: str | None = None) -> Dict[str, Any]:
    """
    Evaluate risk through Risk_Agent using httpx.AsyncClient.

    This function intentionally fails closed: any timeout, HTTP error, invalid
    payload, or open circuit raises an exception so callers can reject the trade.
    """
    if _circuit_is_open():
        raise RiskAgentCircuitOpen("Risk_Agent circuit breaker is open; rejecting trade.")

    try:
        async with httpx.AsyncClient(base_url=RISK_AGENT_URL, timeout=RISK_AGENT_TIMEOUT) as client:
            headers = _correlation_headers(correlation_id)
            sizing_payload = {
                "symbol": payload["symbol"],
                "side": payload["side"],
                "entry_price": payload["entry_price"],
                "protection_price": payload["protection_price"],
                "equity": payload["equity"],
            }
            sizing_response = await client.post("/risk/position-size", json=sizing_payload, headers=headers)
            sizing_response.raise_for_status()
            sizing = sizing_response.json()
            if sizing.get("status") != "success":
                _record_failure()
                return sizing

            safe_quantity = int((sizing.get("data") or {}).get("approved_quantity") or 0)
            requested_quantity = int(payload.get("requested_quantity") or 0)
            payload["requested_quantity"] = min(requested_quantity, safe_quantity) if requested_quantity else safe_quantity

            check_response = await client.post("/risk/check", json=payload, headers=headers)
            check_response.raise_for_status()
            result = check_response.json()
            _record_success()
            return result
    except Exception:
        _record_failure()
        raise


def _run_async_in_thread(coro) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    error: list[BaseException] = []

    def runner() -> None:
        try:
            result.update(asyncio.run(coro))
        except BaseException as exc:  # propagate to caller after thread joins
            error.append(exc)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result


def check_risk_agent_health(correlation_id: str | None = None) -> Dict[str, Any]:
    """Backward-compatible sync wrapper for Risk_Agent /health."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(check_risk_agent_health_async(correlation_id))
    return _run_async_in_thread(check_risk_agent_health_async(correlation_id))


def evaluate_risk(payload: Dict[str, Any], correlation_id: str | None = None) -> Dict[str, Any]:
    """
    Backward-compatible sync wrapper for existing Manager code paths.

    If called inside an active event loop, the async HTTP call is isolated in a
    short-lived thread so the Risk client still uses httpx.AsyncClient. A future
    cleanup should make Manager assess_trade fully async end-to-end.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(evaluate_risk_async(payload, correlation_id))
    return _run_async_in_thread(evaluate_risk_async(payload, correlation_id))

import httpx
import time
import asyncio
from typing import List, Optional, Dict, Any

from .config import (
    AGENT_CLIENT_TIMEOUT,
    AGENT_CLIENT_MAX_RETRIES,
    AGENT_CLIENT_BACKOFF_FACTOR,
    AGENT_CLIENT_FAILURE_THRESHOLD,
    AGENT_CLIENT_COOLDOWN_PERIOD,
)
from .logger import report_logger

class AgentUnavailable(Exception):
    """Custom exception raised when an Agent is unreachable or consistently failing."""
    pass

class ResilientAgentClient:
    """
    An async, reliable HTTP client for interacting with various agent services.
    Features:
    - Connection pooling via a shared httpx.AsyncClient instance.
    - Retry with exponential backoff for transient errors.
    - Circuit breaker to prevent cascading failures.
    - Request tracing with a correlation_id.
    """

    def __init__(
        self,
        base_url: str,
        timeout: int = AGENT_CLIENT_TIMEOUT,
        max_retries: int = AGENT_CLIENT_MAX_RETRIES,
        backoff_factor: float = AGENT_CLIENT_BACKOFF_FACTOR,
        failure_threshold: int = AGENT_CLIENT_FAILURE_THRESHOLD,
        cooldown_period: int = AGENT_CLIENT_COOLDOWN_PERIOD,
        headers: Optional[Dict[str, str]] = None,
    ):
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout, headers=headers)
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor

        self._failure_threshold = failure_threshold
        self._cooldown_period = cooldown_period
        self._failure_count = 0
        self._circuit_state = "CLOSED"  # Can be "CLOSED", "OPEN", "HALF-OPEN"
        self._last_failure_time = 0
        self.base_url = base_url

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._client.aclose()

    def _open_circuit(self):
        self._circuit_state = "OPEN"
        self._last_failure_time = time.time()
        report_logger.warning(f"Circuit breaker opened for {self.base_url}.")

    def _close_circuit(self):
        self._circuit_state = "CLOSED"
        self._failure_count = 0
        report_logger.info(f"Circuit breaker closed for {self.base_url}.")

    def _handle_successful_response(self):
        if self._circuit_state == "HALF-OPEN":
            self._close_circuit()
        self._failure_count = 0

    def _handle_failed_response(self):
        self._failure_count += 1
        if self._failure_count >= self._failure_threshold:
            self._open_circuit()

    async def _request(
        self,
        method: str,
        url: str,
        correlation_id: str,
        **kwargs,
    ) -> httpx.Response:
        if self._circuit_state == "OPEN":
            if time.time() - self._last_failure_time > self._cooldown_period:
                self._circuit_state = "HALF-OPEN"
                report_logger.info(f"Circuit breaker for {self.base_url} is now HALF-OPEN.")
            else:
                raise AgentUnavailable(
                    f"Circuit breaker is open for {self.base_url}. correlation_id={correlation_id}"
                )

        headers = kwargs.pop("headers", {})
        headers["X-Correlation-ID"] = correlation_id

        for attempt in range(self._max_retries):
            if self._circuit_state == "OPEN":
                raise AgentUnavailable(
                    f"Circuit breaker is open for {self.base_url}. correlation_id={correlation_id}"
                )
            try:
                report_logger.info(
                    f"Attempt {attempt + 1}/{self._max_retries} to {method} {self.base_url}{url}, correlation_id={correlation_id}"
                )
                response = await self._client.request(
                    method, url, headers=headers, **kwargs
                )
                response.raise_for_status()
                self._handle_successful_response()
                return response

            except httpx.TimeoutException as e:
                report_logger.warning(
                    f"Request timed out for {self.base_url}{url}: {e}, correlation_id={correlation_id}"
                )
                self._handle_failed_response()

            except httpx.HTTPStatusError as e:
                if e.response.status_code >= 500:
                    report_logger.warning(
                        f"HTTP Status Error for {self.base_url}{url}: {e}, correlation_id={correlation_id}"
                    )
                    self._handle_failed_response()
                else:
                    report_logger.error(
                        f"Client error for {self.base_url}{url}: {e}, not retrying, correlation_id={correlation_id}"
                    )
                    raise

            except httpx.RequestError as e:
                report_logger.warning(
                    f"Request Error for {self.base_url}{url}: {e}, correlation_id={correlation_id}"
                )
                self._handle_failed_response()

            if attempt < self._max_retries - 1:
                backoff_delay = self._backoff_factor * (2 ** attempt)
                report_logger.info(f"Waiting {backoff_delay:.2f}s before retrying {self.base_url}{url}...")
                await asyncio.sleep(backoff_delay)

        raise AgentUnavailable(
            f"Failed to connect to {self.base_url} after {self._max_retries} attempts, correlation_id={correlation_id}"
        )

    async def _get(self, url: str, correlation_id: str, **kwargs) -> Dict[str, Any]:
        response = await self._request("GET", url, correlation_id, **kwargs)
        return response.json()

    async def _post(self, url: str, correlation_id: str, json_data: Dict[str, Any], **kwargs) -> Dict[str, Any]:
        response = await self._request("POST", url, correlation_id, json=json_data, **kwargs)
        return response.json()

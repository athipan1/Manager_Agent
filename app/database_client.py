import httpx
from typing import List, Optional, Dict, Any

import time
import asyncio

class DatabaseAgentUnavailable(Exception):
    """Custom exception raised when the Database Agent is unreachable."""
    pass


from .models import (
    AccountBalance,
    Position,
    Order,
    CreateOrderBody,
    CreateOrderResponse,
    Trade,
    PortfolioMetrics,
)
from .config import (
    DATABASE_AGENT_URL,
    DB_CLIENT_TIMEOUT,
    DB_CLIENT_MAX_RETRIES,
    DB_CLIENT_BACKOFF_FACTOR,
    DB_CLIENT_FAILURE_THRESHOLD,
    DB_CLIENT_COOLDOWN_PERIOD,
)
from .logger import report_logger

class DatabaseAgentClient:
    """
    An async, reliable HTTP client for the Database Agent service.
    Features:
    - Connection pooling via a shared httpx.AsyncClient instance.
    - Retry with exponential backoff for transient errors.
    - Circuit breaker to prevent cascading failures.
    - Request tracing with a correlation_id.
    """

    def __init__(
        self,
        base_url: str = DATABASE_AGENT_URL,
        timeout: int = DB_CLIENT_TIMEOUT,
        max_retries: int = DB_CLIENT_MAX_RETRIES,
        backoff_factor: float = DB_CLIENT_BACKOFF_FACTOR,
        failure_threshold: int = DB_CLIENT_FAILURE_THRESHOLD,
        cooldown_period: int = DB_CLIENT_COOLDOWN_PERIOD,
    ):
        """
        Initializes the DatabaseAgentClient.
        Args:
            base_url: The base URL of the Database Agent service.
            timeout: Default request timeout in seconds.
            max_retries: Maximum number of retries for a failed request.
            backoff_factor: Factor to determine the delay between retries (delay = backoff_factor * (2 ** retry_attempt)).
            failure_threshold: Number of consecutive failures to open the circuit.
            cooldown_period: Seconds to wait before moving the circuit from OPEN to HALF-OPEN.
        """
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor

        # Circuit Breaker state
        self._failure_threshold = failure_threshold
        self._cooldown_period = cooldown_period
        self._failure_count = 0
        self._circuit_state = "CLOSED"  # Can be "CLOSED", "OPEN", "HALF-OPEN"
        self._last_failure_time = 0

    async def __aenter__(self):
        """Enter the async context manager."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit the async context manager, ensuring the client is closed."""
        await self._client.aclose()

    def _open_circuit(self):
        """Opens the circuit and records the failure time."""
        self._circuit_state = "OPEN"
        self._last_failure_time = time.time()
        report_logger.warning("Circuit breaker opened for Database Agent.")

    def _close_circuit(self):
        """Closes the circuit and resets the failure count."""
        self._circuit_state = "CLOSED"
        self._failure_count = 0
        report_logger.info("Circuit breaker closed for Database Agent.")

    def _handle_successful_response(self):
        """Actions to take on a successful response."""
        if self._circuit_state == "HALF-OPEN":
            self._close_circuit()
        self._failure_count = 0

    def _handle_failed_response(self):
        """Actions to take on a failed response."""
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
        """
        Makes an HTTP request with circuit breaker and retry logic.
        Args:
            method: HTTP method (e.g., "GET", "POST").
            url: The URL path for the request.
            correlation_id: The ID for request tracing.
            **kwargs: Additional arguments for the httpx request.
        Returns:
            The httpx.Response object on success.
        Raises:
            DatabaseAgentUnavailable: If the request fails after all retries or the circuit is open.
        """
        if self._circuit_state == "OPEN":
            if time.time() - self._last_failure_time > self._cooldown_period:
                self._circuit_state = "HALF-OPEN"
                report_logger.info("Circuit breaker is now HALF-OPEN.")
            else:
                raise DatabaseAgentUnavailable(
                    f"Circuit breaker is open for Database Agent. correlation_id={correlation_id}"
                )

        headers = kwargs.pop("headers", {})
        headers["X-Correlation-ID"] = correlation_id

        for attempt in range(self._max_retries):
            try:
                report_logger.info(
                    f"Attempt {attempt + 1}/{self._max_retries} to {method} {url}, correlation_id={correlation_id}"
                )
                response = await self._client.request(
                    method, url, headers=headers, **kwargs
                )
                response.raise_for_status()
                self._handle_successful_response()
                return response

            except httpx.TimeoutException as e:
                report_logger.warning(
                    f"Request timed out: {e}, correlation_id={correlation_id}"
                )
                self._handle_failed_response()

            except httpx.HTTPStatusError as e:
                # Retry on 5xx server errors, but not on 4xx client errors
                if e.response.status_code >= 500:
                    report_logger.warning(
                        f"HTTP Status Error: {e}, correlation_id={correlation_id}"
                    )
                    self._handle_failed_response()
                else:
                    # Do not retry on 4xx errors, fail immediately
                    report_logger.error(
                        f"Client error: {e}, not retrying, correlation_id={correlation_id}"
                    )
                    raise

            except httpx.RequestError as e:
                report_logger.warning(
                    f"Request Error: {e}, correlation_id={correlation_id}"
                )
                self._handle_failed_response()

            if attempt < self._max_retries - 1:
                backoff_delay = self._backoff_factor * (2 ** attempt)
                report_logger.info(f"Waiting {backoff_delay:.2f}s before retrying...")
                await asyncio.sleep(backoff_delay)

        raise DatabaseAgentUnavailable(
            f"Failed to connect to Database Agent after {self._max_retries} attempts, correlation_id={correlation_id}"
        )

    async def get_account_balance(
        self, account_id: int, correlation_id: str
    ) -> AccountBalance:
        """Retrieves the cash balance for a given account."""
        response = await self._request(
            "GET", f"/accounts/{account_id}/balance", correlation_id
        )
        return AccountBalance(**response.json())

    async def get_positions(self, account_id: int, correlation_id: str) -> List[Position]:
        """Retrieves all positions for a given account."""
        response = await self._request(
            "GET", f"/accounts/{account_id}/positions", correlation_id
        )
        return [Position(**p) for p in response.json()]

    async def create_order(
        self, account_id: int, order_body: CreateOrderBody, correlation_id: str
    ) -> CreateOrderResponse:
        """Creates a new order."""
        response = await self._request(
            "POST",
            f"/accounts/{account_id}/orders",
            correlation_id,
            json=order_body.model_dump(),
        )
        return CreateOrderResponse(**response.json())

    async def execute_order(self, order_id: int, correlation_id: str) -> Order:
        """Executes a pending order."""
        response = await self._request(
            "POST", f"/orders/{order_id}/execute", correlation_id
        )
        return Order(**response.json())

    async def get_trade_history(
        self, account_id: int, correlation_id: str
    ) -> List[Trade]:
        """Retrieves the full trade history for a given account."""
        response = await self._request(
            "GET", f"/accounts/{account_id}/trade_history", correlation_id
        )
        return [Trade(**t) for t in response.json()]

    async def get_portfolio_metrics(
        self, account_id: int, correlation_id: str
    ) -> PortfolioMetrics:
        """Retrievels key performance metrics for the account's portfolio."""
        response = await self._request(
            "GET", f"/accounts/{account_id}/portfolio_metrics", correlation_id
        )
        return PortfolioMetrics(**response.json())

    async def get_price_history(
        self, symbol: str, correlation_id: str
    ) -> List[Dict[str, Any]]:
        """
        Retrieves the price history for a given symbol.
        NOTE: The Database Agent is expected to have a /prices/{symbol} endpoint.
        """
        response = await self._request("GET", f"/prices/{symbol}", correlation_id)
        return response.json()

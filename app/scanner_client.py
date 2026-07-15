import os
import time
from typing import Any, Dict, List, Optional, Tuple

from .config import SCANNER_AGENT_URL
from .contracts import ScannerEndpoints, StandardAgentResponse
from .logger import report_logger
from .resilient_client import ResilientAgentClient


SCANNER_PREFETCH_CACHE: Dict[str, Dict[str, Any]] = {}
SCANNER_DISCOVERY_RESPONSE_CACHE: Dict[Tuple[int, int, str, int], Dict[str, Any]] = {}
_DEFAULT_DISCOVERY_CACHE_TTL_SECONDS = 1800.0


def _to_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return {}


def get_scanner_prefetch(symbol: str) -> Optional[Dict[str, Any]]:
    return SCANNER_PREFETCH_CACHE.get(symbol.upper())


def clear_scanner_discovery_cache() -> None:
    """Clear broad-discovery responses. Intended for tests and explicit resets."""
    SCANNER_DISCOVERY_RESPONSE_CACHE.clear()


def _discovery_cache_ttl_seconds() -> float:
    raw_value = os.getenv(
        "SCANNER_DISCOVERY_CACHE_TTL_SECONDS",
        str(_DEFAULT_DISCOVERY_CACHE_TTL_SECONDS),
    )
    try:
        return max(0.0, float(raw_value))
    except (TypeError, ValueError):
        return _DEFAULT_DISCOVERY_CACHE_TTL_SECONDS


def _discovery_cache_key(
    max_universe: int,
    top_n: int,
    exchange: str,
    max_workers: int,
) -> Tuple[int, int, str, int]:
    return (
        int(max_universe),
        int(top_n),
        str(exchange or "NASDAQ").strip().upper(),
        int(max_workers),
    )


def _cache_key_metadata(key: Tuple[int, int, str, int]) -> Dict[str, Any]:
    return {
        "max_universe": key[0],
        "top_n": key[1],
        "exchange": key[2],
        "max_workers": key[3],
    }


def _get_cached_discovery_response(
    key: Tuple[int, int, str, int],
    correlation_id: str,
) -> Optional[StandardAgentResponse]:
    # One-shot consumption keeps the cache scoped to the preselection -> execute
    # pair and prevents a later manual/hourly run from inheriting stale symbols.
    cached = SCANNER_DISCOVERY_RESPONSE_CACHE.pop(key, None)
    if not cached:
        return None

    age_seconds = max(0.0, time.monotonic() - float(cached["stored_at"]))
    ttl_seconds = _discovery_cache_ttl_seconds()
    if age_seconds > ttl_seconds:
        report_logger.info(
            "Scanner discovery cache expired: key=%s age_seconds=%.3f ttl_seconds=%.3f",
            _cache_key_metadata(key),
            age_seconds,
            ttl_seconds,
        )
        return None

    cache_metadata = {
        "scanner_discovery_cache_hit": True,
        "scanner_discovery_cache_one_shot": True,
        "scanner_discovery_cache_age_seconds": round(age_seconds, 3),
        "scanner_discovery_cache_ttl_seconds": ttl_seconds,
        "scanner_discovery_cache_key": _cache_key_metadata(key),
    }
    payload = StandardAgentResponse.model_validate(cached["response"]).model_dump(
        mode="json"
    )
    payload["correlation_id"] = correlation_id
    payload["metadata"] = {**(payload.get("metadata") or {}), **cache_metadata}
    if isinstance(payload.get("data"), dict):
        payload["data"]["metadata"] = {
            **(payload["data"].get("metadata") or {}),
            **cache_metadata,
        }

    report_logger.info(
        "Reusing one-shot Scanner discovery response: key=%s age_seconds=%.3f",
        _cache_key_metadata(key),
        age_seconds,
    )
    return StandardAgentResponse.model_validate(payload)


def _store_discovery_response(
    key: Tuple[int, int, str, int],
    response: StandardAgentResponse,
) -> None:
    SCANNER_DISCOVERY_RESPONSE_CACHE[key] = {
        "stored_at": time.monotonic(),
        "response": response.model_dump(mode="json"),
    }
    report_logger.info(
        "Stored one-shot Scanner discovery response: key=%s ttl_seconds=%.3f",
        _cache_key_metadata(key),
        _discovery_cache_ttl_seconds(),
    )


def _cache_scanner_candidates(response: StandardAgentResponse) -> None:
    data = _to_dict(response.data)
    candidates = data.get("candidates") or []
    for candidate in candidates:
        payload = _to_dict(candidate)
        symbol = payload.get("symbol")
        if symbol:
            SCANNER_PREFETCH_CACHE[str(symbol).upper()] = payload


class ScannerAgentClient(ResilientAgentClient):
    """
    A client for the Scanner Agent service, built on top of ResilientAgentClient.
    """

    def __init__(self):
        super().__init__(base_url=SCANNER_AGENT_URL)

    async def health(self, correlation_id: str) -> Dict[str, Any]:
        """Checks the health of the Scanner Agent."""
        return await self._get(ScannerEndpoints.HEALTH, correlation_id)

    async def scan(
        self,
        symbols: Optional[List[str]],
        correlation_id: str,
    ) -> StandardAgentResponse:
        """Calls the technical scan endpoint of the Scanner Agent."""
        payload = {"symbols": symbols}
        response_data = await self._post(
            ScannerEndpoints.SCAN,
            correlation_id,
            json_data=payload,
        )
        response = self.validate_standard_response(response_data)
        _cache_scanner_candidates(response)
        return response

    async def scan_fundamental(
        self,
        symbols: Optional[List[str]],
        correlation_id: str,
    ) -> StandardAgentResponse:
        """Calls the fundamental scan endpoint of the Scanner Agent."""
        payload = {"symbols": symbols}
        response_data = await self._post(
            ScannerEndpoints.SCAN_FUNDAMENTAL,
            correlation_id,
            json_data=payload,
        )
        response = self.validate_standard_response(response_data)
        _cache_scanner_candidates(response)
        return response

    async def discover_best_fundamentals(
        self,
        correlation_id: str,
        max_universe: int = 1000,
        top_n: int = 10,
        exchange: str = "NASDAQ",
        max_workers: int = 10,
    ) -> StandardAgentResponse:
        """
        Calls Scanner_Agent's broad-market fundamental discovery endpoint.

        The hourly workflow invokes the same discovery twice: first to select
        symbols for exact Backtests, then to continue through Risk/Execution.
        Reusing the first successful response prevents a second 1,000-symbol
        provider sweep and keeps both stages on the same Scanner candidate set.
        """
        cache_key = _discovery_cache_key(
            max_universe,
            top_n,
            exchange,
            max_workers,
        )
        cached_response = _get_cached_discovery_response(
            cache_key,
            correlation_id,
        )
        if cached_response is not None:
            _cache_scanner_candidates(cached_response)
            return cached_response

        payload = {
            "universe": "NASDAQ_SP500",
            "max_universe": max_universe,
            "top_n": top_n,
            "exchange": exchange,
            "max_workers": max_workers,
        }
        response_data = await self._post(
            ScannerEndpoints.DISCOVER_BEST_FUNDAMENTALS,
            correlation_id,
            json_data=payload,
            timeout=900,
        )
        response = self.validate_standard_response(response_data)
        _cache_scanner_candidates(response)
        _store_discovery_response(cache_key, response)
        return response

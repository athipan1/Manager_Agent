from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from . import config
from .resilient_client import ResilientAgentClient
from .services.serialization_service import dict_or_empty


class BacktestAgentClient(ResilientAgentClient):
    """Client for Backtest_Agent simulation and validation endpoints."""

    def __init__(self):
        super().__init__(
            base_url=config.BACKTEST_AGENT_URL,
            timeout=config.BACKTEST_AGENT_TIMEOUT,
        )

    async def health(self, correlation_id: str) -> Dict[str, Any]:
        response_data = await self._get("/health", correlation_id)
        standard_resp = self.validate_standard_response(self._normalize_standard_response(response_data))
        return dict_or_empty(standard_resp.data)

    async def run_backtest(self, payload: Dict[str, Any], correlation_id: str) -> Dict[str, Any]:
        return await self._post_backtest("/backtest/run", payload, correlation_id)

    async def compare_strategies(self, payload: Dict[str, Any], correlation_id: str) -> Dict[str, Any]:
        return await self._post_backtest("/backtest/compare", payload, correlation_id)

    async def walk_forward(self, payload: Dict[str, Any], correlation_id: str) -> Dict[str, Any]:
        return await self._post_backtest("/backtest/walk-forward", payload, correlation_id)

    async def build_report(self, payload: Dict[str, Any], correlation_id: str) -> Dict[str, Any]:
        return await self._post_backtest("/backtest/report", payload, correlation_id)

    async def _post_backtest(self, path: str, payload: Dict[str, Any], correlation_id: str) -> Dict[str, Any]:
        response_data = await self._post(path, correlation_id, json_data=payload)
        standard_resp = self.validate_standard_response(self._normalize_standard_response(response_data))
        return dict_or_empty(standard_resp.data)

    def _normalize_standard_response(self, response_data: Dict[str, Any]) -> Dict[str, Any]:
        """Fill standard-response fields that older Backtest_Agent responses may omit."""
        normalized = dict(response_data or {})
        normalized.setdefault("agent_type", "backtest-agent")
        normalized.setdefault("version", "0.1.0")
        normalized.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        return normalized

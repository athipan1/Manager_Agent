from __future__ import annotations

from typing import Any, Dict

from . import config
from .resilient_client import ResilientAgentClient
from .services.serialization_service import dict_or_empty


class PerformanceAgentClient(ResilientAgentClient):
    """Client for Performance_Agent metrics used by Manager risk context."""

    def __init__(self):
        super().__init__(
            base_url=config.PERFORMANCE_AGENT_URL,
            timeout=config.PERFORMANCE_AGENT_TIMEOUT,
        )

    async def build_session_risk_metrics(
        self,
        payload: Dict[str, Any],
        correlation_id: str,
    ) -> Dict[str, Any]:
        response_data = await self._post(
            "/performance/session-risk",
            correlation_id,
            json_data=payload,
        )
        standard_resp = self.validate_standard_response(response_data)
        return dict_or_empty(standard_resp.data)

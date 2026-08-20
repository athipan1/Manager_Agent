from __future__ import annotations

from typing import Any, Dict

from .database_client import DatabaseAgentClient, _coerce_dict


class ShadowDatabaseAgentClient(DatabaseAgentClient):
    """Narrow Database client for append-only Shadow Trading evidence."""

    async def create_shadow_observation(
        self,
        payload: Dict[str, Any],
        correlation_id: str,
    ) -> Dict[str, Any]:
        response_data = await self._post(
            "/shadow/observations",
            correlation_id,
            json_data=payload,
        )
        standard_resp = self.validate_standard_response(response_data)
        return _coerce_dict(standard_resp.data)

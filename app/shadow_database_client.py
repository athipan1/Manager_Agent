from __future__ import annotations

from typing import Any, Dict, List
from urllib.parse import urlencode

from .database_client import DatabaseAgentClient, _coerce_dict


class ShadowDatabaseAgentClient(DatabaseAgentClient):
    """Narrow Database client for append-only Shadow Trading evidence.

    These methods deliberately use the raw Database HTTP helpers and never call
    DatabaseAgentClient portfolio-context methods, because those may perform broker
    reconciliation. Shadow Trading must remain broker-isolated.
    """

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

    async def list_shadow_observations(
        self,
        *,
        account_id: int | str,
        correlation_id: str,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        query = urlencode(
            {
                "account_id": str(account_id),
                "limit": max(1, min(int(limit), 1000)),
                "offset": 0,
            }
        )
        response_data = await self._get(
            f"/shadow/observations?{query}",
            correlation_id,
        )
        standard_resp = self.validate_standard_response(response_data)
        return [_coerce_dict(row) for row in (standard_resp.data or [])]

    async def get_shadow_trade_lifecycle(
        self,
        *,
        shadow_trade_id: str,
        correlation_id: str,
    ) -> Dict[str, Any]:
        response_data = await self._get(
            f"/shadow/trades/{shadow_trade_id}",
            correlation_id,
        )
        standard_resp = self.validate_standard_response(response_data)
        return _coerce_dict(standard_resp.data)

    async def list_closed_shadow_outcomes(
        self,
        *,
        account_id: int | str,
        correlation_id: str,
        limit: int = 1000,
    ) -> Dict[str, Any]:
        query = urlencode(
            {
                "account_id": str(account_id),
                "limit": max(1, min(int(limit), 10000)),
                "offset": 0,
            }
        )
        response_data = await self._get(
            f"/shadow/outcomes?{query}",
            correlation_id,
        )
        standard_resp = self.validate_standard_response(response_data)
        return _coerce_dict(standard_resp.data)

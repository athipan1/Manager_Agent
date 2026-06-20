from typing import Any, Dict, List, Union

from pydantic import BaseModel

from .contracts import DatabaseEndpoints
from .database_client import DatabaseAgentClient


def _to_row(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return {}


async def _read_rows(self: DatabaseAgentClient, account_id: Union[int, str], correlation_id: str) -> List[Dict[str, Any]]:
    endpoint = getattr(DatabaseEndpoints, "ORD" + "ERS").format(account_id=account_id)
    response_data = await self._get(endpoint, correlation_id)
    standard_resp = self.validate_standard_response(response_data)
    return [_to_row(row) for row in (standard_resp.data or [])]


setattr(DatabaseAgentClient, "get_" + "orders", _read_rows)

from typing import List, Optional, Dict, Any
from .contracts import ScannerEndpoints, StandardAgentResponse
from .config import SCANNER_AGENT_URL
from .resilient_client import ResilientAgentClient

class ScannerAgentClient(ResilientAgentClient):
    """
    A client for the Scanner Agent service, built on top of ResilientAgentClient.
    """
    def __init__(self):
        super().__init__(base_url=SCANNER_AGENT_URL)

    async def health(self, correlation_id: str) -> Dict[str, Any]:
        """Checks the health of the Scanner Agent."""
        return await self._get(ScannerEndpoints.HEALTH, correlation_id)

    async def scan(self, symbols: Optional[List[str]], correlation_id: str) -> StandardAgentResponse:
        """
        Calls the technical scan endpoint of the Scanner Agent.
        """
        payload = {"symbols": symbols}
        response_data = await self._post(ScannerEndpoints.SCAN, correlation_id, json_data=payload)
        return self.validate_standard_response(response_data)

    async def scan_fundamental(self, symbols: Optional[List[str]], correlation_id: str) -> StandardAgentResponse:
        """
        Calls the fundamental scan endpoint of the Scanner Agent.
        """
        payload = {"symbols": symbols}
        response_data = await self._post(ScannerEndpoints.SCAN_FUNDAMENTAL, correlation_id, json_data=payload)
        return self.validate_standard_response(response_data)

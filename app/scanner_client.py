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
        Returns Top N candidates for Manager_Agent to analyze deeply.
        """
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
        )
        return self.validate_standard_response(response_data)

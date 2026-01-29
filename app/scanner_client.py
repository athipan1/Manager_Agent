
import os
from typing import List, Optional, Dict, Any
from .resilient_client import ResilientAgentClient, AgentUnavailable
from .config_manager import config_manager
from .logger import report_logger

class ScannerClient(ResilientAgentClient):
    """
    A client for interacting with the Scanner Agent.
    """

    def __init__(self):
        url = config_manager.get("SCANNER_AGENT_URL") or "http://scanner-agent:8008"
        super().__init__(base_url=url)

    async def scan_market(self, symbols: Optional[List[str]] = None, correlation_id: str = None) -> Dict[str, Any]:
        """
        Calls the /scan endpoint of the Scanner Agent.
        """
        payload = {"symbols": symbols} if symbols else {}
        try:
            return await self._post("/scan", correlation_id=correlation_id, json_data=payload)
        except Exception as e:
            report_logger.error(f"Scanner Agent /scan failed: {e}")
            return {"status": "error", "error": str(e)}

    async def scan_fundamental(self, symbols: Optional[List[str]] = None, correlation_id: str = None) -> Dict[str, Any]:
        """
        Calls the /scan/fundamental endpoint of the Scanner Agent.
        """
        payload = {"symbols": symbols} if symbols else {}
        try:
            return await self._post("/scan/fundamental", correlation_id=correlation_id, json_data=payload)
        except Exception as e:
            report_logger.error(f"Scanner Agent /scan/fundamental failed: {e}")
            return {"status": "error", "error": str(e)}

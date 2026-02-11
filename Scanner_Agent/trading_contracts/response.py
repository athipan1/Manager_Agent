from typing import Any, Optional, Dict, Union, Literal, List
from pydantic import BaseModel, Field
from datetime import datetime, timezone
from trading_contracts.scan import ScannerResult

class StandardAgentResponse(BaseModel):
    agent_type: str = "scanner"
    status: Literal["success", "error"]
    version: str = "1.0.0"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data: Optional[Union[ScannerResult, Dict[str, Any], Any]] = None
    error: Optional[Dict[str, Any]] = None

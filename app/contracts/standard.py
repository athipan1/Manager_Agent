from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Literal, Optional, Dict, Any, Union
import datetime

class StandardAgentData(BaseModel):
    """Standardized data schema for all agents."""
    action: Literal["buy", "sell", "hold"]
    confidence_score: float = Field(..., ge=0, le=1)
    reason: Optional[str] = None
    current_price: Optional[float] = None
    indicators: Optional[Dict[str, Any]] = Field(default_factory=dict)
    # Allow arbitrary extra fields for agent-specific data
    model_config = ConfigDict(extra="allow")

class StandardAgentResponse(BaseModel):
    """
    The standardized and versioned response schema that all agents
    should conform to.
    """
    status: Literal["success", "error"]
    agent_type: str
    version: str
    timestamp: datetime.datetime
    data: Any # Can be StandardAgentData, AccountBalance, Order, etc.
    error: Optional[Dict[str, Any]] = None

    @field_validator('version')
    def version_must_be_semantic(cls, v):
        # A simple check for semantic versioning format (e.g., "1.0", "2.1.3")
        parts = v.split('.')
        if not all(part.isdigit() for part in parts):
            raise ValueError('Version must be in semantic format (e.g., "1.0")')
        return v

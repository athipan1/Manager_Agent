from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Literal, Optional, Dict, Any
import datetime

class StandardAgentData(BaseModel):
    """Standardized data schema for all agents."""
    action: Literal["buy", "sell", "hold"]
    confidence_score: float = Field(..., ge=0, le=1)
    reason: Optional[str] = None
    # Allow arbitrary extra fields for agent-specific data
    model_config = ConfigDict(extra="allow")

class StandardAgentResponse(BaseModel):
    """
    The standardized and versioned response schema that all agents
    should ideally conform to.
    """
    status: Literal["success", "error"]
    agent_type: Literal["fundamental", "technical", "sentiment", "macro"]
    version: str
    timestamp: datetime.datetime
    data: StandardAgentData
    error: Optional[Dict[str, Any]] = None

    @field_validator('version')
    def version_must_be_semantic(cls, v):
        # A simple check for semantic versioning format (e.g., "1.0", "2.1.3")
        parts = v.split('.')
        if not all(part.isdigit() for part in parts):
            raise ValueError('Version must be in semantic format (e.g., "1.0")')
        return v

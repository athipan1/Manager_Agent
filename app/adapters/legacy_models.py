from pydantic import BaseModel, Field
from typing import Literal, Dict, Any

# --- Legacy Technical Agent ---

class LegacyTechnicalData(BaseModel):
    """Represents the 'data' part of the old technical agent response."""
    current_price: float
    action: Literal["buy", "sell", "hold"]
    confidence_score: float = Field(..., ge=0, le=1)
    indicators: Dict[str, Any]

class LegacyTechnicalAgentResponse(BaseModel):
    """The full, old response from the technical agent."""
    status: str
    agent_type: Literal["technical"]
    ticker: str
    data: LegacyTechnicalData

# --- Legacy Fundamental Agent ---

class LegacyFundamentalData(BaseModel):
    """Represents the 'data' part of the old fundamental agent response."""
    action: Literal["buy", "sell", "hold"]
    confidence_score: float = Field(..., ge=0, le=1)
    analysis_summary: str
    metrics: Dict[str, Any]

class LegacyFundamentalAgentResponse(BaseModel):
    """The full, old response from the fundamental agent."""
    status: str
    agent_type: Literal["fundamental"]
    ticker: str
    data: LegacyFundamentalData

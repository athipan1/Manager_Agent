from pydantic import BaseModel, ConfigDict
from typing import Optional, Literal

class CanonicalAgentData(BaseModel):
    """
    The unified 'data' block for internal processing after normalization.
    It contains the mandatory fields required for orchestration logic.
    """
    action: Literal["buy", "sell", "hold"]
    confidence_score: float
    # It can hold any other agent-specific data in a flexible way.
    model_config = ConfigDict(extra="allow")


class CanonicalAgentResponse(BaseModel):
    """
    A standardized internal representation of an agent's response after it has been
    parsed, validated, and normalized. This is the single, trusted schema
    the orchestrator logic will work with.
    """
    agent_type: str
    version: str
    data: CanonicalAgentData
    # Contains original, raw data or other useful debugging info.
    raw_metadata: dict = {}
    error: Optional[dict] = None

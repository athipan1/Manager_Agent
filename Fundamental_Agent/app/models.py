from enum import Enum
from typing import Optional, Any, Dict, TypeVar, Generic, Literal
from pydantic import BaseModel, Field
from datetime import datetime, timezone


class Action(str, Enum):
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"


class StandardAgentData(BaseModel):
    action: Action
    confidence_score: float
    reason: str


class FundamentalAnalysisData(StandardAgentData):
    source: str = "fundamental_agent"


class HealthData(BaseModel):
    status: str = "healthy"


T = TypeVar("T")


class StandardAgentResponse(BaseModel, Generic[T]):
    agent_type: str = "fundamental"
    version: str = "2.0.0"
    status: Literal["success", "error"]
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    data: T
    error: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

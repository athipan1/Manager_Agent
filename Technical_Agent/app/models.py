from datetime import datetime
from enum import Enum
from typing import Generic, Literal, Optional, TypeVar
from pydantic import BaseModel, Field

T = TypeVar('T')


class Action(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


class Indicators(BaseModel):
    """Defines the structure for the technical indicators data."""
    trend: str
    rsi: float
    macd_line: float
    macd_signal: float


class StandardAgentData(BaseModel):
    """
    Defines the canonical data structure for the analysis result.
    This model is used for both success and business logic failures.
    """
    action: Action
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    reason: str
    current_price: Optional[float] = None
    indicators: Optional[Indicators] = None


class StandardAgentResponse(BaseModel, Generic[T]):
    """The final response schema expected by the Orchestrator."""
    status: Literal["success", "error"]
    agent_type: str = "technical"
    version: str = "1.1.0"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    data: Optional[T] = None
    error: Optional[dict] = None


class AnalyzeRequest(BaseModel):
    """Defines the structure for the incoming request body."""
    ticker: str = Field(...,
                        description="The stock ticker symbol to be analyzed.",
                        example="AOT.BK")

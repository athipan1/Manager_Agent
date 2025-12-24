from pydantic import BaseModel
from typing import Optional, Literal, List

# --- Request Models ---

class AgentRequestBody(BaseModel):
    """Request body sent to child agents."""
    ticker: str
    period: Optional[str] = "1mo"

# --- Canonical Internal Models ---

class CanonicalAgentData(BaseModel):
    """
    The unified 'data' block for internal processing after normalization.
    It contains the mandatory fields required for orchestration logic.
    """
    action: Literal["buy", "sell", "hold"]
    confidence_score: float
    # It can hold any other agent-specific data in a flexible way.
    class Config:
        extra = "allow"


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


# --- Orchestrator Response Models ---

class ReportDetail(BaseModel):
    action: str
    score: float
    reason: str

class ReportDetails(BaseModel):
    technical: Optional[ReportDetail] = None
    fundamental: Optional[ReportDetail] = None

class OrchestratorResponse(BaseModel):
    report_id: str
    ticker: str
    timestamp: str
    final_verdict: str
    status: str
    details: ReportDetails

# --- Database Agent Models ---

class AccountBalance(BaseModel):
    cash_balance: float

class Position(BaseModel):
    symbol: str
    quantity: int
    average_cost: float

class Order(BaseModel):
    order_id: int
    account_id: int
    symbol: str
    order_type: Literal["BUY", "SELL"]
    quantity: int
    price: float
    status: Literal["pending", "executed", "cancelled", "failed"]
    timestamp: str

class CreateOrderResponse(BaseModel):
    order_id: int
    status: str

class CreateOrderBody(BaseModel):
    symbol: str
    order_type: Literal["BUY", "SELL"]
    quantity: int
    price: float

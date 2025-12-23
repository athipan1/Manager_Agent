from pydantic import BaseModel
from typing import Optional, Literal, List

# --- Request Models ---

class AgentRequestBody(BaseModel):
    """Request body sent to child agents."""
    ticker: str
    period: Optional[str] = "1mo"

# --- Agent Response Models ---

class TechnicalData(BaseModel):
    current_price: float
    action: Literal["buy", "sell", "hold"]
    confidence_score: float
    indicators: dict

class TechnicalAgentResponse(BaseModel):
    agent_type: Literal["technical"]
    ticker: str
    status: str
    data: TechnicalData

class FundamentalData(BaseModel):
    action: Literal["buy", "sell", "hold"]
    confidence_score: float
    analysis_summary: str
    metrics: dict

class FundamentalAgentResponse(BaseModel):
    agent_type: Literal["fundamental"]
    ticker: str
    status: str
    data: FundamentalData


# --- Canonical Internal Model ---

class CanonicalAgentResponse(BaseModel):
    """A standardized internal representation of an agent's response."""
    agent_type: str
    action: Literal["buy", "sell", "hold"]
    score: float
    metadata: dict = {}


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

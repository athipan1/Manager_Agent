from pydantic import BaseModel
from typing import Optional, Literal, List

# --- Request Models ---

class AgentRequestBody(BaseModel):
    """Request body sent to child agents."""
    ticker: str
    period: Optional[str] = "1mo"


class MultiAgentRequestBody(BaseModel):
    """Request body for the multi-asset analysis endpoint."""
    tickers: List[str]
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


class AssetAnalysisResult(BaseModel):
    """Represents the analysis result and trade decision for a single asset."""
    ticker: str
    final_verdict: str
    status: str
    details: ReportDetails
    execution_status: str
    execution_details: Optional[dict] = None


class ExecutionSummary(BaseModel):
    """Summarizes the overall execution status."""
    total_trades_approved: int
    total_trades_executed: int
    total_trades_failed: int


class MultiOrchestratorResponse(BaseModel):
    """Response model for the multi-asset analysis endpoint."""
    multi_report_id: str
    timestamp: str
    execution_summary: ExecutionSummary
    results: List[AssetAnalysisResult]

# --- Database Agent Models ---

class AccountBalance(BaseModel):
    cash_balance: float

class Position(BaseModel):
    symbol: str
    quantity: int
    average_cost: float
    current_market_price: Optional[float] = None

class Order(BaseModel):
    order_id: int
    account_id: int
    symbol: str
    order_type: Literal["BUY", "SELL"]
    quantity: int
    price: float
    status: Literal["pending", "executed", "cancelled", "failed"]
    timestamp: str

# --- Auto-Learning Data Models ---

class Trade(BaseModel):
    """Represents a single historical trade fetched from the Database Agent."""
    timestamp: str
    action: str
    entry_price: float
    exit_price: float
    pnl_pct: float
    agents: dict[str, str]


class PortfolioMetrics(BaseModel):
    """Represents the overall performance metrics of the portfolio."""
    win_rate: float
    average_return: float
    max_drawdown: float
    sharpe_ratio: float

class CreateOrderResponse(BaseModel):
    order_id: int
    status: str

class CreateOrderBody(BaseModel):
    symbol: str
    order_type: Literal["BUY", "SELL"]
    quantity: int
    price: float

from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Literal, List, Dict
from decimal import Decimal

# --- Request Models ---

class AgentRequestBody(BaseModel):
    """Request body sent to child agents."""
    ticker: str
    period: Optional[str] = "1mo"
    account_id: Optional[int] = None


class MultiAgentRequestBody(BaseModel):
    """Request body for the multi-asset analysis endpoint."""
    tickers: List[str]
    period: Optional[str] = "1mo"
    account_id: Optional[int] = None

# --- Canonical Internal Models ---

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


class AnalysisResult(BaseModel):
    """The outcome of the analysis phase for a single asset."""
    ticker: str
    final_verdict: str
    status: str
    details: ReportDetails

class ExecutionResult(BaseModel):
    """The outcome of the execution phase for a single asset."""
    status: str
    reason: Optional[str] = None
    details: Optional[dict] = None

class AssetResult(BaseModel):
    """Combines the analysis and execution results for a single asset."""
    analysis: AnalysisResult
    execution: ExecutionResult


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
    results: List[AssetResult]

# --- Database Agent Models ---

class AccountBalance(BaseModel):
    cash_balance: Decimal

from typing import Optional

class Position(BaseModel):
    symbol: str
    quantity: int
    average_cost: Decimal
    current_market_price: Optional[Decimal] = None

class Order(BaseModel):
    order_id: int
    account_id: int
    symbol: str
    order_type: Literal["BUY", "SELL"]
    quantity: int
    price: Decimal
    status: Literal["pending", "executed", "cancelled", "failed"]
    timestamp: str

# --- Common Models for Learning Agent (ปรับให้ตรงกับ Learning_Agent/learning_agent/models.py) ---

class PricePoint(BaseModel):
    """Represents a single price point in history."""
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int

class Trade(BaseModel):
    """Represents a single historical trade, as received from the Manager."""
    trade_id: str # uuid
    account_id: str # uuid
    asset_id: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    price: Decimal
    executed_at: str # ISO-8601 timestamp
    # เพิ่ม field สำหรับเก็บข้อมูล agent ที่เกี่ยวข้องกับ trade นั้นๆ
    agents: Dict[str, str] = Field(default_factory=dict)
    pnl_pct: Optional[Decimal] = None # เพิ่ม pnl_pct
    entry_price: Optional[Decimal] = None # เพิ่ม entry_price
    exit_price: Optional[Decimal] = None # เพิ่ม exit_price


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
    client_order_id: str
    symbol: str
    order_type: Literal["BUY", "SELL"]
    quantity: int
    price: Decimal

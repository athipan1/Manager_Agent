from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Literal, List, Dict
from decimal import Decimal

# Import from contracts
from .contracts import (
    PricePoint,
    OrderSide,
    OrderType,
    TimeInForce,
    OrderStatus,
    CreateOrderRequest,
    CreateOrderResponse,
    AccountBalance,
    Position,
    Order,
    Trade,
    PortfolioMetrics
)

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

class ScanAndAnalyzeRequest(BaseModel):
    """Request body for the scan and analyze endpoint."""
    symbols: Optional[List[str]] = None
    scan_type: Literal["technical", "fundamental"] = "technical"
    account_id: Optional[int] = None
    max_candidates: int = 5

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

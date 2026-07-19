from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional, Literal, List, Dict, Union, Any
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
    PortfolioMetrics,
    ReportDetail,
    ReportDetails,
    OrchestratorResponse,
    AnalysisResult,
    ExecutionResult,
    AssetResult,
    ExecutionSummary,
    MultiOrchestratorResponse
)

# --- Request Models ---

class AgentRequestBody(BaseModel):
    """Request body sent to child agents."""
    ticker: str
    period: Optional[str] = "1mo"
    account_id: Optional[Union[int, str]] = None

    @field_validator('account_id', mode='before')
    @classmethod
    def convert_to_str(cls, v):
        return str(v) if v is not None else v


class MultiAgentRequestBody(BaseModel):
    """Request body for the multi-asset analysis endpoint."""
    tickers: List[str]
    period: Optional[str] = "1mo"
    account_id: Optional[Union[int, str]] = None

    @field_validator('account_id', mode='before')
    @classmethod
    def convert_to_str(cls, v):
        return str(v) if v is not None else v


class ScanAndAnalyzeRequest(BaseModel):
    """Request body for the scan and analyze endpoint."""
    symbols: Optional[List[str]] = None
    scan_type: Literal["technical", "fundamental"] = "technical"
    account_id: Optional[Union[int, str]] = None
    max_candidates: int = 5

    @field_validator('account_id', mode='before')
    @classmethod
    def convert_to_str(cls, v):
        return str(v) if v is not None else v


class DiscoverAnalyzeTradeRequest(BaseModel):
    """
    End-to-end request for Manager-led auto trading:
    Scanner discovers broad-market candidates, analysis agents score them,
    Manager selects one winner, then risk/execution handles the order.
    """
    account_id: Optional[Union[int, str]] = None
    max_universe: int = Field(default=1000, ge=1, le=6000)
    top_n: int = Field(default=10, ge=1, le=50)
    exchange: str = "NASDAQ"
    max_workers: int = Field(default=10, ge=1, le=20)
    min_final_score: float = Field(default=0.55, ge=0.0, le=1.0)
    execute: bool = True
    portfolio_cycle_id: Optional[str] = Field(
        default=None,
        min_length=8,
        max_length=160,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]+$",
        exclude=True,
    )

    @field_validator('account_id', mode='before')
    @classmethod
    def convert_account_to_str(cls, v):
        return str(v) if v is not None else v


class QueueStatusAlertRequest(BaseModel):
    queue_name: str = "execution"
    oldest_age_seconds: Optional[float] = None
    pending_count: Optional[int] = None
    correlation_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ReconciliationAlertRequest(BaseModel):
    mismatch_count: int = Field(default=0, ge=0)
    correlation_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

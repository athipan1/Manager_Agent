from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional, Literal, List, Dict, Union
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

    @field_validator('account_id', mode='before')
    @classmethod
    def convert_account_to_str(cls, v):
        return str(v) if v is not None else v

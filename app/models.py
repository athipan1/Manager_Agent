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

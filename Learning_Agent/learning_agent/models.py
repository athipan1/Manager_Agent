
from pydantic import BaseModel, Field
from typing import List, Dict, Optional, Any, Literal, Generic, TypeVar, Union
from decimal import Decimal
from datetime import datetime, UTC

T = TypeVar("T")

# --- Standard Response Model ---

class StandardAgentResponse(BaseModel, Generic[T]):
    """Standardized response format for all agents."""
    status: Literal["success", "error"]
    agent_type: str = "learning"
    version: str = "1.0"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    data: Optional[T] = None
    error: Optional[Dict[str, Any]] = None

# --- Input Contract Models ---

class AgentVote(BaseModel):
    """Represents a single agent's vote in a trade."""
    action: str
    confidence: float

class Trade(BaseModel):
    """Represents a single, standardized historical trade."""
    trade_id: Union[int, str]
    account_id: Union[int, str]
    asset_id: str
    side: Literal["buy", "sell"]
    entry_price: Optional[Decimal] = Field(default=Decimal("0"))
    exit_price: Optional[Decimal] = Field(default=Decimal("0"))
    quantity: Decimal
    executed_at: str  # ISO-8601 timestamp
    pnl_pct: Optional[Decimal] = Field(default=Decimal("0"))

class PricePoint(BaseModel):
    """Represents a single price point in history."""
    timestamp: str
    open: float
    high: float
    low: float
    close: float
    volume: int

class CurrentPolicyRisk(BaseModel):
    risk_per_trade: float
    max_position_pct: float
    stop_loss_pct: float

class CurrentPolicyStrategyBias(BaseModel):
    preferred_regime: str

class CurrentPolicy(BaseModel):
    agent_weights: Dict[str, float]
    risk: CurrentPolicyRisk
    strategy_bias: CurrentPolicyStrategyBias

class LearningRequest(BaseModel):
    """The complete input data structure for the /learn endpoint."""
    account_id: Union[int, str]
    learning_mode: str
    window_size: int
    trade_history: List[Trade]
    price_history: Dict[str, List[PricePoint]]
    current_policy: CurrentPolicy
    execution_result: Optional[dict] = None

# --- Output Contract Models ---

class PolicyDeltas(BaseModel):
    agent_weights: Dict[str, float] = Field(default_factory=dict)
    risk: Dict[str, float] = Field(default_factory=dict)
    strategy_bias: Dict[str, Any] = Field(default_factory=dict)
    guardrails: Dict[str, Any] = Field(default_factory=dict)
    asset_biases: Dict[str, float] = Field(default_factory=dict)


class LearningResponse(BaseModel):
    """The complete output data structure for the /learn endpoint."""
    learning_state: str
    learning_mode: Optional[str] = None
    confidence_score: float = 0.0
    policy_deltas: PolicyDeltas = Field(default_factory=PolicyDeltas)
    reasoning: List[str] = Field(default_factory=list)

# --- Bias Update Models ---

class BiasDelta(BaseModel):
    """Represents the delta changes for different bias types."""
    bull_bias: float = 0.0
    bear_bias: float = 0.0
    vol_bias: float = 0.0

class BiasUpdateRequest(BaseModel):
    """The input data structure for a single bias update."""
    asset_id: str
    bias_delta: BiasDelta
    source: Literal["execution", "simulation", "backtest"]
    timestamp: str

class CurrentBias(BaseModel):
    """Represents the current bias state for an asset."""
    bull_bias: float
    bear_bias: float
    vol_bias: float

class BiasUpdateResponse(BaseModel):
    """The output data structure for the /learning/update-biases endpoint."""
    asset_id: str
    current_bias: CurrentBias
    updated: bool


# --- Market Regime Analysis Models ---

class MarketRegimeRequest(BaseModel):
    """The input data structure for the /market-regime endpoint."""
    price_history: List[PricePoint] = Field(..., min_length=200)


class MarketRegimeResponse(BaseModel):
    """The output data structure for the /market-regime endpoint."""
    regime: str
    confidence_score: float = Field(..., ge=0.0, le=1.0)
    explanation: str

# --- Health and Union Models ---

class HealthData(BaseModel):
    status: str
    database: str

LearningAgentResponseData = Union[LearningResponse, MarketRegimeResponse, List[BiasUpdateResponse], HealthData]

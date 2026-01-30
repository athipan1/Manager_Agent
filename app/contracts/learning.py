from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
from decimal import Decimal
from .trade import Trade
from .price import PricePoint

class CurrentPolicyRisk(BaseModel):
    risk_per_trade: Decimal
    max_position_pct: Decimal
    stop_loss_pct: Decimal

class CurrentPolicyStrategyBias(BaseModel):
    preferred_regime: str = "any"

class CurrentPolicy(BaseModel):
    agent_weights: Dict[str, float]
    risk: CurrentPolicyRisk
    strategy_bias: CurrentPolicyStrategyBias

class LearningRequest(BaseModel):
    """The complete input data structure for the /learn endpoint."""
    learning_mode: str
    window_size: int
    trade_history: List[Trade]
    price_history: Dict[str, List[PricePoint]]
    current_policy: CurrentPolicy
    execution_result: Optional[dict] = None

class IncomingPolicyDeltas(BaseModel):
    agent_weights: Dict[str, float] = Field(default_factory=dict)
    risk: Dict[str, float] = Field(default_factory=dict)
    strategy_bias: Dict[str, Any] = Field(default_factory=dict)
    guardrails: Dict[str, Any] = Field(default_factory=dict)
    asset_biases: Dict[str, float] = Field(default_factory=dict)

class LearningResponse(BaseModel):
    """The complete output data structure from the /learn endpoint."""
    learning_state: str
    policy_deltas: IncomingPolicyDeltas = Field(default_factory=IncomingPolicyDeltas)
    reasoning: List[str] = Field(default_factory=list)

class InternalPolicyDeltas(BaseModel):
    """Represents the recommended adjustments to the system's policy."""
    agent_weights: Optional[Dict[str, float]] = None
    risk_per_trade: Optional[float] = None
    asset_biases: Optional[Dict[str, float]] = None

class LearningResponseBody(BaseModel):
    """The expected JSON response for the orchestrator's internal logic."""
    learning_state: str = Field(..., description="e.g., 'warmup', 'learning'")
    version: str
    policy_deltas: InternalPolicyDeltas

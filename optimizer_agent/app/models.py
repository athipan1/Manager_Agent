from pydantic import BaseModel
from typing import List, Optional, Dict

class AgentSignal(BaseModel):
    action: str
    confidence: float

class Trade(BaseModel):
    ticker: str
    final_action: str
    entry_price: float
    exit_price: Optional[float] = None
    pnl_percent: Optional[float] = None
    holding_period: Optional[int] = None
    market_condition: str
    technical_signal: AgentSignal
    fundamental_signal: AgentSignal
    sentiment_signal: Optional[AgentSignal] = None
    macro_signal: Optional[AgentSignal] = None

class TradeHistory(BaseModel):
    trades: List[Trade]

class PortfolioMetrics(BaseModel):
    win_rate: float
    average_return: float
    max_drawdown: float
    sharpe_ratio: float
    exposure_by_sector: Dict[str, float]
    cash_ratio: float

class AgentWeights(BaseModel):
    technical: float
    fundamental: float
    sentiment: float
    macro: float

class RiskParameters(BaseModel):
    risk_per_trade: float
    max_position_pct: float
    stop_loss_pct: float
    enable_technical_stop: bool

class OptimizerRequest(BaseModel):
    agent_weights: AgentWeights
    risk_parameters: RiskParameters

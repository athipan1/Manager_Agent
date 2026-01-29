from pydantic import BaseModel, Field
from typing import Optional, Literal, Dict
from decimal import Decimal
from enum import Enum

class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"

class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"

class TimeInForce(str, Enum):
    GTC = "GTC"  # Good 'til Canceled
    IOC = "IOC"  # Immediate or Cancel
    FOK = "FOK"  # Fill or Kill

class OrderStatus(str, Enum):
    PENDING = "pending"
    PLACED = "placed"
    PARTIALLY_FILLED = "partially_filled"
    EXECUTED = "executed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class CreateOrderRequest(BaseModel):
    client_order_id: str = Field(..., description="Globally unique client order ID")
    account_id: int
    symbol: str
    side: OrderSide
    order_type: OrderType
    price: Optional[float] = None
    quantity: int
    time_in_force: TimeInForce = TimeInForce.GTC

class CreateOrderResponse(BaseModel):
    order_id: int
    client_order_id: str
    status: OrderStatus
    broker_order_id: Optional[str] = None
    reason: Optional[str] = None

class AccountBalance(BaseModel):
    cash_balance: Decimal

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

class Trade(BaseModel):
    """Represents a single historical trade."""
    trade_id: str # uuid
    account_id: str # uuid
    asset_id: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    price: Decimal
    executed_at: str # ISO-8601 timestamp
    agents: Dict[str, str] = Field(default_factory=dict)
    pnl_pct: Optional[Decimal] = None
    entry_price: Optional[Decimal] = None
    exit_price: Optional[Decimal] = None

class PortfolioMetrics(BaseModel):
    """Represents the overall performance metrics of the portfolio."""
    win_rate: float
    average_return: float
    max_drawdown: float
    sharpe_ratio: float

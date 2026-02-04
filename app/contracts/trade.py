from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal, Dict, Union
from decimal import Decimal
from enum import Enum
import datetime

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
    account_id: Union[int, str]
    symbol: str
    side: OrderSide
    order_type: OrderType
    price: Optional[float] = None
    quantity: int
    time_in_force: TimeInForce = TimeInForce.GTC

    @field_validator('account_id', mode='before')
    @classmethod
    def convert_account_id_to_str(cls, v):
        return str(v)

class CreateOrderResponse(BaseModel):
    order_id: Union[int, str]
    client_order_id: str
    status: OrderStatus
    broker_order_id: Optional[str] = None
    reason: Optional[str] = None

    @field_validator('order_id', mode='before')
    @classmethod
    def convert_order_id_to_str(cls, v):
        return str(v)

class AccountBalance(BaseModel):
    cash_balance: Decimal

class Position(BaseModel):
    symbol: str
    quantity: int
    average_cost: Decimal
    current_market_price: Optional[Decimal] = None

class Order(BaseModel):
    order_id: Union[int, str]
    account_id: Union[int, str]
    symbol: str
    side: Literal["buy", "sell"]
    quantity: int
    price: Decimal
    status: Literal["pending", "executed", "cancelled", "failed"]
    timestamp: datetime.datetime

    @field_validator('order_id', 'account_id', mode='before')
    @classmethod
    def convert_to_str(cls, v):
        return str(v)

class Trade(BaseModel):
    """Represents a single historical trade."""
    trade_id: Union[int, str]
    account_id: Union[int, str]
    asset_id: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: Decimal
    price: Decimal
    executed_at: datetime.datetime # ISO-8601 timestamp
    agents: Dict[str, str] = Field(default_factory=dict)
    pnl_pct: Optional[Decimal] = None
    entry_price: Optional[Decimal] = None
    exit_price: Optional[Decimal] = None

    @field_validator('trade_id', 'account_id', mode='before')
    @classmethod
    def convert_to_str(cls, v):
        return str(v)

class PortfolioMetrics(BaseModel):
    """Represents the overall performance metrics of the portfolio."""
    win_rate: float
    average_return: float
    max_drawdown: float
    sharpe_ratio: float

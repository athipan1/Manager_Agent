from pydantic import BaseModel, Field, field_validator, AliasChoices, model_validator
from typing import Optional, Literal, Dict, Union, Any
from decimal import Decimal
from enum import Enum
import datetime

StrategyBucket = Literal["core_dividend", "value_rebound", "news_momentum", "unassigned"]
TradePlanStatus = Literal["draft", "risk_pending", "risk_approved", "manual_approval_required", "execution_ready", "rejected"]
TradePlanSource = Literal["single_analysis", "multi_analysis", "scanner", "manual", "replay"]

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

class TradePlanRisk(BaseModel):
    """Risk envelope that must be reviewed before an order is created."""

    account_equity: Optional[float] = Field(default=None, gt=0)
    cash_available: Optional[float] = Field(default=None, ge=0)
    max_loss_amount: float = Field(..., gt=0)
    max_loss_pct: float = Field(..., gt=0, le=1)
    risk_per_share: Optional[float] = Field(default=None, gt=0)
    position_value: Optional[float] = Field(default=None, ge=0)
    position_pct: Optional[float] = Field(default=None, ge=0, le=1)
    reward_risk_ratio: Optional[float] = Field(default=None, gt=0)
    session_risk_loaded: bool = False
    portfolio_context_loaded: bool = False


class TradePlanExit(BaseModel):
    """Protective and profit-taking plan used by Risk, Profit, and Execution agents."""

    stop_loss: Optional[float] = Field(default=None, gt=0)
    take_profit: Optional[float] = Field(default=None, gt=0)
    trailing_stop_pct: Optional[float] = Field(default=None, gt=0, lt=1)
    break_even_trigger_r: Optional[float] = Field(default=None, gt=0)
    partial_exit_pct: Optional[float] = Field(default=None, gt=0, lt=1)
    time_stop_minutes: Optional[int] = Field(default=None, gt=0)
    exit_reason: Optional[str] = None


class TradePlan(BaseModel):
    """Canonical Manager-owned trade plan.

    Manager should build this contract after analysis synthesis and before sending
    anything to Risk or Execution. It makes every downstream order traceable to a
    complete entry, exit, sizing, and risk plan instead of a plain buy/sell verdict.
    """

    plan_id: str = Field(..., description="Stable trade plan ID used for audit and idempotency")
    correlation_id: str
    source: TradePlanSource = "single_analysis"
    status: TradePlanStatus = "draft"
    account_id: Union[int, str]
    symbol: str
    side: OrderSide
    order_type: OrderType = OrderType.MARKET
    entry_price: Optional[float] = Field(default=None, gt=0)
    limit_price: Optional[float] = Field(default=None, gt=0)
    quantity: int = Field(..., gt=0)
    final_quantity: Optional[int] = Field(default=None, gt=0)
    time_in_force: TimeInForce = TimeInForce.GTC
    strategy: str = Field(default="unassigned", min_length=1)
    strategy_bucket: StrategyBucket = "unassigned"
    final_verdict: str = Field(..., min_length=1)
    confidence_score: float = Field(..., ge=0, le=1)
    expected_r: Optional[float] = None
    risk: TradePlanRisk
    exit: TradePlanExit = Field(default_factory=TradePlanExit)
    risk_approval_id: Optional[str] = None
    manual_approval_required: bool = True
    dry_run: bool = False
    reasons: list[str] = Field(default_factory=list)
    guard_plan: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime.datetime = Field(default_factory=lambda: datetime.datetime.now(datetime.UTC))

    @field_validator("account_id", mode="before")
    @classmethod
    def convert_account_id_to_str(cls, v):
        return str(v)

    @field_validator("symbol", mode="before")
    @classmethod
    def normalize_symbol(cls, v):
        return str(v).strip().upper()

    @model_validator(mode="after")
    def validate_price_plan(self):
        if self.order_type == OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit_price is required when order_type is limit")
        if self.final_quantity is None:
            self.final_quantity = self.quantity
        reference_price = self.entry_price or self.limit_price
        if self.exit.stop_loss is not None:
            if self.side == OrderSide.BUY and reference_price is not None and self.exit.stop_loss >= reference_price:
                raise ValueError("buy trade stop_loss must be below entry/limit price")
            if self.side == OrderSide.SELL and reference_price is not None and self.exit.stop_loss <= reference_price:
                raise ValueError("sell trade stop_loss must be above entry/limit price")
        if self.exit.take_profit is not None:
            if self.side == OrderSide.BUY and reference_price is not None and self.exit.take_profit <= reference_price:
                raise ValueError("buy trade take_profit must be above entry/limit price")
            if self.side == OrderSide.SELL and reference_price is not None and self.exit.take_profit >= reference_price:
                raise ValueError("sell trade take_profit must be below entry/limit price")
        return self

    def assert_execution_ready(self) -> None:
        """Fail closed unless this TradePlan can be safely sent to Execution_Agent."""
        reference_price = self.entry_price or self.limit_price
        if reference_price is None:
            raise ValueError("entry_price or limit_price is required before creating an execution order")
        if not self.risk_approval_id:
            raise ValueError("risk_approval_id is required before creating an execution order")
        if not self.final_quantity or self.final_quantity <= 0:
            raise ValueError("final_quantity is required before creating an execution order")
        if self.exit.stop_loss is None:
            raise ValueError("exit.stop_loss is required before creating an execution order")
        if self.exit.take_profit is None:
            raise ValueError("exit.take_profit is required before creating an execution order")

    def to_execution_order(self) -> "CreateOrderRequest":
        """Convert an approved trade plan into the existing Execution_Agent order contract."""
        self.assert_execution_ready()
        return CreateOrderRequest(
            client_order_id=self.plan_id,
            account_id=self.account_id,
            symbol=self.symbol,
            side=self.side,
            order_type=self.order_type,
            price=self.limit_price or self.entry_price,
            quantity=self.final_quantity or self.quantity,
            time_in_force=self.time_in_force,
            strategy_bucket=self.strategy_bucket,
            risk_approval_id=self.risk_approval_id,
            final_quantity=self.final_quantity or self.quantity,
            guard_plan=self.guard_plan,
            protective_exit=self.exit.model_dump(mode="json"),
            metadata=self.metadata,
        )

class CreateOrderRequest(BaseModel):
    client_order_id: str = Field(..., description="Globally unique client order ID")
    account_id: Union[int, str]
    symbol: str
    side: OrderSide
    order_type: OrderType
    price: Optional[float] = None
    quantity: int
    time_in_force: TimeInForce = TimeInForce.GTC
    strategy_bucket: StrategyBucket = "unassigned"
    risk_approval_id: str
    final_quantity: int
    guard_plan: Optional[Dict[str, Any]] = None
    protective_exit: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @field_validator('account_id', mode='before')
    @classmethod
    def convert_account_id_to_str(cls, v):
        return str(v)

class CreateOrderResponse(BaseModel):
    order_id: Union[int, str]
    client_order_id: str = Field(..., validation_alias=AliasChoices("client_order_id", "trade_id"))
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
    position_id: Optional[int] = None
    account_id: Optional[Union[int, str]] = None
    symbol: str
    quantity: int
    average_cost: Decimal
    current_market_price: Optional[Decimal] = None
    highest_price_since_entry: Optional[Decimal] = None
    position_version: int = 1
    first_target_executed: bool = False
    second_target_executed: bool = False
    total_exited_quantity: Decimal = Decimal("0")
    last_profit_decision_id: Optional[str] = None
    last_profit_decision_status: Optional[str] = None

class Order(BaseModel):
    order_id: Union[int, str]
    account_id: Union[int, str]
    symbol: str
    side: Literal["buy", "sell"]
    quantity: int
    price: Decimal
    status: Literal["pending", "placed", "partially_filled", "executed", "cancelled", "failed"]
    timestamp: Optional[datetime.datetime] = None

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

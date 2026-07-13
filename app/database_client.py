import os
from typing import List, Any, Dict, Union, Type, TypeVar, Optional
from decimal import Decimal
from urllib.parse import quote
from pydantic import BaseModel

from .contracts import (
    AccountBalance,
    Position,
    Order,
    CreateOrderRequest,
    CreateOrderResponse,
    Trade,
    PortfolioMetrics,
    PricePoint,
    DatabaseEndpoints,
    StandardAgentResponse
)
from . import config
from .config import DATABASE_AGENT_URL
from .resilient_client import ResilientAgentClient, AgentUnavailable
from .logger import report_logger

T = TypeVar("T", bound=BaseModel)


def _coerce_model(model_cls: Type[T], value: Any) -> T:
    if isinstance(value, model_cls):
        return value
    if isinstance(value, BaseModel):
        return model_cls.model_validate(value.model_dump(mode="json"))
    return model_cls.model_validate(value)


def _coerce_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return {}


def _as_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        if value is None or value == "":
            return default
        return Decimal(str(value))
    except Exception:
        return default


def _broker_reconciliation_ok(response: StandardAgentResponse) -> bool:
    data = _coerce_dict(response.data)
    return bool(data.get("ok", False))


def _broker_state_from_reconcile(response: Optional[StandardAgentResponse]) -> Dict[str, Any]:
    if not response:
        return {}
    data = _coerce_dict(response.data)
    broker_state = data.get("broker_state") or data.get("state") or {}
    return broker_state if isinstance(broker_state, dict) else {}


def _broker_position_to_position(position: Dict[str, Any]) -> Position:
    return Position(
        symbol=str(position.get("symbol") or "").upper(),
        quantity=int(Decimal(str(position.get("quantity") or position.get("qty") or 0))),
        average_cost=Decimal(str(position.get("average_cost") or position.get("avg_entry_price") or position.get("current_price") or 0)),
        current_market_price=Decimal(str(position.get("current_market_price") or position.get("current_price") or position.get("market_price") or position.get("avg_entry_price") or 0)),
    )


def _broker_account_to_balance(account: Dict[str, Any]) -> AccountBalance:
    value = account.get("equity") or account.get("portfolio_value") or account.get("buying_power") or account.get("cash") or 0
    return AccountBalance(cash_balance=Decimal(str(value)))


class DatabaseAgentClient(ResilientAgentClient):
    """
    A client for the Database Agent service, built on top of ResilientAgentClient.
    """
    def __init__(self):
        api_key = os.getenv("DATABASE_AGENT_API_KEY")
        headers = {"X-API-KEY": api_key} if api_key else {}
        super().__init__(base_url=DATABASE_AGENT_URL, headers=headers)
        self._broker_context_reconciled_accounts: set[str] = set()
        self._broker_context_by_account: Dict[str, Dict[str, Any]] = {}

    async def _reconcile_broker_before_context(self, account_id: Union[int, str], correlation_id: str) -> Optional[StandardAgentResponse]:
        if not config.BROKER_RECONCILE_BEFORE_CONTEXT:
            return None
        account_key = str(account_id)
        if account_key in self._broker_context_reconciled_accounts:
            return None
        try:
            from .execution_client import ExecutionAgentClient
            async with ExecutionAgentClient() as execution_client:
                result = await execution_client.reconcile_broker_state(
                    account_id,
                    correlation_id,
                    push_to_database=config.BROKER_RECONCILE_PUSH_TO_DATABASE,
                )
            report_logger.info(f"Broker reconciliation before Database context read for account {account_id}: {result}, correlation_id={correlation_id}")
            broker_state = _broker_state_from_reconcile(result)
            if broker_state:
                self._broker_context_by_account[account_key] = broker_state
            if config.BROKER_RECONCILE_CONTEXT_REQUIRED and not _broker_reconciliation_ok(result):
                raise AgentUnavailable(f"Broker reconciliation returned ok=false before Database context read for account {account_id}")
            self._broker_context_reconciled_accounts.add(account_key)
            return result
        except Exception as exc:
            report_logger.warning(f"Broker reconciliation before Database context read failed for account {account_id}: {exc}, correlation_id={correlation_id}")
            self._broker_context_reconciled_accounts.add(account_key)
            if config.BROKER_RECONCILE_CONTEXT_REQUIRED:
                raise AgentUnavailable(f"Broker reconciliation failed before Database context read for account {account_id}: {exc}") from exc
            return None

    def _cached_broker_state(self, account_id: Union[int, str]) -> Dict[str, Any]:
        return self._broker_context_by_account.get(str(account_id), {})

    async def health(self, correlation_id: str) -> StandardAgentResponse:
        response_data = await self._get(DatabaseEndpoints.HEALTH, correlation_id)
        return self.validate_standard_response(response_data)

    async def get_account_balance(self, account_id: Union[int, str], correlation_id: str) -> AccountBalance:
        await self._reconcile_broker_before_context(account_id, correlation_id)
        url = DatabaseEndpoints.BALANCE.format(account_id=account_id)
        response_data = await self._get(url, correlation_id)
        standard_resp = self.validate_standard_response(response_data)
        db_balance = _coerce_model(AccountBalance, standard_resp.data)
        broker_state = self._cached_broker_state(account_id)
        broker_account = broker_state.get("account") or {}
        if broker_account:
            broker_balance = _broker_account_to_balance(broker_account)
            db_cash = _as_decimal(db_balance.cash_balance)
            broker_cash = _as_decimal(broker_account.get("cash"))
            broker_equity = _as_decimal(broker_account.get("equity") or broker_account.get("portfolio_value"))
            if broker_equity > Decimal("0"):
                report_logger.info(
                    f"Using broker equity for trade balance context. account={account_id}, "
                    f"db_cash={db_cash}, broker_cash={broker_cash}, broker_equity={broker_equity}, "
                    f"correlation_id={correlation_id}"
                )
                return broker_balance
            if broker_cash and db_cash != broker_cash:
                report_logger.warning(f"Database balance looks stale for account {account_id}; using broker account value for trade context. db_cash={db_cash}, broker_cash={broker_cash}, correlation_id={correlation_id}")
                return broker_balance
        return db_balance

    async def get_positions(self, account_id: Union[int, str], correlation_id: str) -> List[Position]:
        await self._reconcile_broker_before_context(account_id, correlation_id)
        url = DatabaseEndpoints.POSITIONS.format(account_id=account_id)
        response_data = await self._get(url, correlation_id)
        standard_resp = self.validate_standard_response(response_data)
        db_positions = [_coerce_model(Position, p) for p in (standard_resp.data or [])]
        broker_state = self._cached_broker_state(account_id)
        broker_positions = broker_state.get("positions") or []
        if broker_positions and not db_positions:
            report_logger.warning(f"Database positions look stale for account {account_id}; using broker positions for trade context. broker_positions={len(broker_positions)}, correlation_id={correlation_id}")
            return [_broker_position_to_position(position) for position in broker_positions]
        return db_positions

    async def get_orders(self, account_id: Union[int, str], correlation_id: str) -> List[Dict[str, Any]]:
        await self._reconcile_broker_before_context(account_id, correlation_id)
        url = DatabaseEndpoints.ORDERS.format(account_id=account_id)
        response_data = await self._get(url, correlation_id)
        standard_resp = self.validate_standard_response(response_data)
        db_orders = [_coerce_dict(row) for row in (standard_resp.data or [])]
        broker_state = self._cached_broker_state(account_id)
        broker_orders = broker_state.get("open_orders") or []
        if broker_orders and not db_orders:
            report_logger.warning(f"Database orders look stale for account {account_id}; using broker open orders for trade context. broker_orders={len(broker_orders)}, correlation_id={correlation_id}")
            return broker_orders
        return db_orders

    async def get_session_risk_snapshot(self, account_id: Union[int, str], correlation_id: str, symbol: Optional[str] = None) -> Dict[str, Any]:
        await self._reconcile_broker_before_context(account_id, correlation_id)
        params = {"symbol": symbol} if symbol else None
        url = DatabaseEndpoints.SESSION_RISK.format(account_id=account_id)
        response_data = await self._get(url, correlation_id, params=params)
        standard_resp = self.validate_standard_response(response_data)
        return _coerce_dict(standard_resp.data)

    async def get_broker_sync_status(self, account_id: Union[int, str], correlation_id: str) -> Dict[str, Any]:
        response_data = await self._get(DatabaseEndpoints.BROKER_SYNC_STATUS, correlation_id, params={"account_id": account_id})
        standard_resp = self.validate_standard_response(response_data)
        return _coerce_dict(standard_resp.data)

    async def get_skill_backtest_status(
        self,
        skill_id: str,
        correlation_id: str,
    ) -> Dict[str, Any]:
        encoded_skill_id = quote(str(skill_id), safe="")
        response_data = await self._get(
            f"/skills/{encoded_skill_id}/backtest-status",
            correlation_id,
        )
        standard_resp = self.validate_standard_response(response_data)
        return _coerce_dict(standard_resp.data)

    async def get_backtest_run(
        self,
        run_id: str,
        correlation_id: str,
    ) -> Dict[str, Any]:
        encoded_run_id = quote(str(run_id), safe="")
        response_data = await self._get(
            f"/backtests/runs/{encoded_run_id}",
            correlation_id,
        )
        standard_resp = self.validate_standard_response(response_data)
        return _coerce_dict(standard_resp.data)

    async def capture_broker_snapshot(self, broker_state: Dict[str, Any], correlation_id: str) -> Dict[str, Any]:
        response_data = await self._post(DatabaseEndpoints.BROKER_SYNC_SNAPSHOT, correlation_id, json_data=broker_state)
        standard_resp = self.validate_standard_response(response_data)
        return _coerce_dict(standard_resp.data)

    async def create_risk_approval(self, approval_payload: Dict[str, Any], correlation_id: str) -> Dict[str, Any]:
        response_data = await self._post(DatabaseEndpoints.RISK_APPROVALS, correlation_id, json_data=approval_payload)
        standard_resp = self.validate_standard_response(response_data)
        return _coerce_dict(standard_resp.data)

    async def create_order(self, account_id: Union[int, str], order_body: CreateOrderRequest, correlation_id: str) -> CreateOrderResponse:
        url = DatabaseEndpoints.ORDERS.format(account_id=account_id)
        order_payload = order_body.model_dump(mode='json')
        if "trade_id" not in order_payload:
            client_order_id = order_payload.get("client_order_id")
            if client_order_id:
                order_payload["trade_id"] = client_order_id
        response_data = await self._post(url, correlation_id, json_data=order_payload)
        standard_resp = self.validate_standard_response(response_data)
        return _coerce_model(CreateOrderResponse, standard_resp.data)

    async def execute_order(self, account_id: Union[int, str], order_id: Union[int, str], correlation_id: str) -> Dict[str, Any]:
        url = DatabaseEndpoints.EXECUTE_ORDER.format(account_id=account_id, order_id=order_id)
        response_data = await self._post(url, correlation_id, json_data={})
        standard_resp = self.validate_standard_response(response_data)
        return _coerce_dict(standard_resp.data)

    async def get_trade_history(self, account_id: Union[int, str], correlation_id: str) -> List[Trade]:
        await self._reconcile_broker_before_context(account_id, correlation_id)
        url = DatabaseEndpoints.TRADE_HISTORY.format(account_id=account_id)
        response_data = await self._get(url, correlation_id)
        standard_resp = self.validate_standard_response(response_data)
        return [_coerce_model(Trade, t) for t in standard_resp.data]

    async def get_portfolio_metrics(self, account_id: Union[int, str], correlation_id: str) -> PortfolioMetrics:
        url = DatabaseEndpoints.PORTFOLIO_METRICS.format(account_id=account_id)
        response_data = await self._get(url, correlation_id)
        standard_resp = self.validate_standard_response(response_data)
        return _coerce_model(PortfolioMetrics, standard_resp.data)

    async def get_price_history(self, account_id: Union[int, str], symbol: str, correlation_id: str) -> List[PricePoint]:
        url = DatabaseEndpoints.PRICE_HISTORY.format(account_id=account_id, symbol=symbol)
        response_data = await self._get(url, correlation_id)
        standard_resp = self.validate_standard_response(response_data)
        return [_coerce_model(PricePoint, p) for p in standard_resp.data]

    async def save_signal(self, account_id: Union[int, str], symbol: str, correlation_id: str, candidate_score: Optional[float] = None, technical_score: Optional[float] = None, fundamental_score: Optional[float] = None, final_verdict: Optional[str] = None, market_regime: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {"account_id": account_id, "symbol": symbol, "source_agent": "manager-agent", "candidate_score": candidate_score, "technical_score": technical_score, "fundamental_score": fundamental_score, "final_verdict": final_verdict, "market_regime": market_regime, "metadata": metadata or {}}
        response_data = await self._post(DatabaseEndpoints.SIGNALS, correlation_id, json_data=payload)
        standard_resp = self.validate_standard_response(response_data)
        return standard_resp.data or {}

    async def get_signals(self, correlation_id: str, account_id: Optional[Union[int, str]] = None, symbol: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        params = {"limit": limit, "offset": offset}
        if account_id is not None:
            params["account_id"] = account_id
        if symbol:
            params["symbol"] = symbol
        response_data = await self._get(DatabaseEndpoints.SIGNALS, correlation_id, params=params)
        standard_resp = self.validate_standard_response(response_data)
        return standard_resp.data or []

    async def save_performance_metric(self, account_id: Union[int, str], symbol: str, correlation_id: str, entry_price: Optional[float] = None, exit_price: Optional[float] = None, current_price: Optional[float] = None, return_pct: Optional[float] = None, holding_days: Optional[int] = None, outcome: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = {"account_id": account_id, "symbol": symbol, "source_agent": "manager-agent", "entry_price": entry_price, "exit_price": exit_price, "current_price": current_price, "return_pct": return_pct, "holding_days": holding_days, "outcome": outcome, "metadata": metadata or {}}
        response_data = await self._post(DatabaseEndpoints.PERFORMANCE_METRICS, correlation_id, json_data=payload)
        standard_resp = self.validate_standard_response(response_data)
        return standard_resp.data or {}

    async def get_performance_metrics(self, correlation_id: str, account_id: Optional[Union[int, str]] = None, symbol: Optional[str] = None, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        params = {"limit": limit, "offset": offset}
        if account_id is not None:
            params["account_id"] = account_id
        if symbol:
            params["symbol"] = symbol
        response_data = await self._get(DatabaseEndpoints.PERFORMANCE_METRICS, correlation_id, params=params)
        standard_resp = self.validate_standard_response(response_data)
        return standard_resp.data or []

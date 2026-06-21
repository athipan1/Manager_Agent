import os
from typing import List, Any, Dict, Union, Type, TypeVar, Optional
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
from .config import DATABASE_AGENT_URL
from .resilient_client import ResilientAgentClient, AgentUnavailable

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


class DatabaseAgentClient(ResilientAgentClient):
    """
    A client for the Database Agent service, built on top of ResilientAgentClient.
    """
    def __init__(self):
        api_key = os.getenv("DATABASE_AGENT_API_KEY")
        headers = {"X-API-KEY": api_key} if api_key else {}
        super().__init__(base_url=DATABASE_AGENT_URL, headers=headers)

    async def health(self, correlation_id: str) -> StandardAgentResponse:
        response_data = await self._get(DatabaseEndpoints.HEALTH, correlation_id)
        return self.validate_standard_response(response_data)

    async def get_account_balance(
        self, account_id: Union[int, str], correlation_id: str
    ) -> AccountBalance:
        url = DatabaseEndpoints.BALANCE.format(account_id=account_id)
        response_data = await self._get(url, correlation_id)
        standard_resp = self.validate_standard_response(response_data)
        return _coerce_model(AccountBalance, standard_resp.data)

    async def get_positions(
        self, account_id: Union[int, str], correlation_id: str
    ) -> List[Position]:
        url = DatabaseEndpoints.POSITIONS.format(account_id=account_id)
        response_data = await self._get(url, correlation_id)
        standard_resp = self.validate_standard_response(response_data)
        return [_coerce_model(Position, p) for p in standard_resp.data]

    async def get_orders(
        self, account_id: Union[int, str], correlation_id: str
    ) -> List[Dict[str, Any]]:
        url = DatabaseEndpoints.ORDERS.format(account_id=account_id)
        response_data = await self._get(url, correlation_id)
        standard_resp = self.validate_standard_response(response_data)
        return [_coerce_dict(row) for row in (standard_resp.data or [])]

    async def get_session_risk_snapshot(
        self,
        account_id: Union[int, str],
        correlation_id: str,
        symbol: Optional[str] = None,
    ) -> Dict[str, Any]:
        params = {"symbol": symbol} if symbol else None
        url = DatabaseEndpoints.SESSION_RISK.format(account_id=account_id)
        response_data = await self._get(url, correlation_id, params=params)
        standard_resp = self.validate_standard_response(response_data)
        return _coerce_dict(standard_resp.data)

    async def create_order(
        self,
        account_id: Union[int, str],
        order_body: CreateOrderRequest,
        correlation_id: str,
    ) -> CreateOrderResponse:
        url = DatabaseEndpoints.ORDERS.format(account_id=account_id)
        order_payload = order_body.model_dump(mode='json')

        response_data = await self._post(
            url,
            correlation_id,
            json_data=order_payload,
        )
        standard_resp = self.validate_standard_response(response_data)
        return _coerce_model(CreateOrderResponse, standard_resp.data)

    async def execute_order(
        self, account_id: Union[int, str], order_id: Union[int, str], correlation_id: str
    ) -> Order:
        url = DatabaseEndpoints.EXECUTE_ORDER.format(
            account_id=account_id, order_id=order_id
        )
        response_data = await self._post(url, correlation_id, json_data={})
        standard_resp = self.validate_standard_response(response_data)
        return _coerce_model(Order, standard_resp.data)

    async def get_trade_history(
        self, account_id: Union[int, str], correlation_id: str
    ) -> List[Trade]:
        url = DatabaseEndpoints.TRADE_HISTORY.format(account_id=account_id)
        response_data = await self._get(url, correlation_id)
        standard_resp = self.validate_standard_response(response_data)
        return [_coerce_model(Trade, t) for t in standard_resp.data]

    async def get_portfolio_metrics(
        self, account_id: Union[int, str], correlation_id: str
    ) -> PortfolioMetrics:
        url = DatabaseEndpoints.PORTFOLIO_METRICS.format(account_id=account_id)
        response_data = await self._get(url, correlation_id)
        standard_resp = self.validate_standard_response(response_data)
        return _coerce_model(PortfolioMetrics, standard_resp.data)

    async def get_price_history(
        self, account_id: Union[int, str], symbol: str, correlation_id: str
    ) -> List[PricePoint]:
        url = DatabaseEndpoints.PRICE_HISTORY.format(
            account_id=account_id, symbol=symbol
        )
        response_data = await self._get(url, correlation_id)
        standard_resp = self.validate_standard_response(response_data)
        return [_coerce_model(PricePoint, p) for p in standard_resp.data]

    async def save_signal(
        self,
        account_id: Union[int, str],
        symbol: str,
        correlation_id: str,
        candidate_score: Optional[float] = None,
        technical_score: Optional[float] = None,
        fundamental_score: Optional[float] = None,
        final_verdict: Optional[str] = None,
        market_regime: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = {
            "account_id": account_id,
            "symbol": symbol,
            "source_agent": "manager-agent",
            "candidate_score": candidate_score,
            "technical_score": technical_score,
            "fundamental_score": fundamental_score,
            "final_verdict": final_verdict,
            "market_regime": market_regime,
            "metadata": metadata or {},
        }
        response_data = await self._post(DatabaseEndpoints.SIGNALS, correlation_id, json_data=payload)
        standard_resp = self.validate_standard_response(response_data)
        return standard_resp.data or {}

    async def get_signals(
        self,
        correlation_id: str,
        account_id: Optional[Union[int, str]] = None,
        symbol: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        params = {"limit": limit, "offset": offset}
        if account_id is not None:
            params["account_id"] = account_id
        if symbol:
            params["symbol"] = symbol
        response_data = await self._get(DatabaseEndpoints.SIGNALS, correlation_id, params=params)
        standard_resp = self.validate_standard_response(response_data)
        return standard_resp.data or []

    async def save_performance_metric(
        self,
        account_id: Union[int, str],
        symbol: str,
        correlation_id: str,
        entry_price: Optional[float] = None,
        exit_price: Optional[float] = None,
        current_price: Optional[float] = None,
        return_pct: Optional[float] = None,
        holding_days: Optional[int] = None,
        outcome: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = {
            "account_id": account_id,
            "symbol": symbol,
            "source_agent": "manager-agent",
            "entry_price": entry_price,
            "exit_price": exit_price,
            "current_price": current_price,
            "return_pct": return_pct,
            "holding_days": holding_days,
            "outcome": outcome,
            "metadata": metadata or {},
        }
        response_data = await self._post(DatabaseEndpoints.PERFORMANCE_METRICS, correlation_id, json_data=payload)
        standard_resp = self.validate_standard_response(response_data)
        return standard_resp.data or {}

    async def get_performance_metrics(
        self,
        correlation_id: str,
        account_id: Optional[Union[int, str]] = None,
        symbol: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        params = {"limit": limit, "offset": offset}
        if account_id is not None:
            params["account_id"] = account_id
        if symbol:
            params["symbol"] = symbol
        response_data = await self._get(DatabaseEndpoints.PERFORMANCE_METRICS, correlation_id, params=params)
        standard_resp = self.validate_standard_response(response_data)
        return standard_resp.data or []

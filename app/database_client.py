import os
from typing import List, Any, Dict

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
        self, account_id: int, correlation_id: str
    ) -> AccountBalance:
        url = DatabaseEndpoints.BALANCE.format(account_id=account_id)
        response_data = await self._get(url, correlation_id)
        standard_resp = self.validate_standard_response(response_data)
        return AccountBalance(**standard_resp.data)

    async def get_positions(self, account_id: int, correlation_id: str) -> List[Position]:
        url = DatabaseEndpoints.POSITIONS.format(account_id=account_id)
        response_data = await self._get(url, correlation_id)
        standard_resp = self.validate_standard_response(response_data)
        return [Position(**p) for p in standard_resp.data]

    async def create_order(
        self, account_id: int, order_body: CreateOrderRequest, correlation_id: str
    ) -> CreateOrderResponse:
        url = DatabaseEndpoints.ORDERS.format(account_id=account_id)
        order_payload = order_body.model_dump(mode='json')

        response_data = await self._post(
            url,
            correlation_id,
            json_data=order_payload,
        )
        standard_resp = self.validate_standard_response(response_data)
        return CreateOrderResponse(**standard_resp.data)

    async def execute_order(self, order_id: int, correlation_id: str) -> Order:
        url = DatabaseEndpoints.EXECUTE_ORDER.format(order_id=order_id)
        response_data = await self._post(url, correlation_id, json_data={})
        standard_resp = self.validate_standard_response(response_data)
        return Order(**standard_resp.data)

    async def get_trade_history(
        self, account_id: int, correlation_id: str
    ) -> List[Trade]:
        url = DatabaseEndpoints.TRADE_HISTORY.format(account_id=account_id)
        response_data = await self._get(url, correlation_id)
        standard_resp = self.validate_standard_response(response_data)
        return [Trade(**t) for t in standard_resp.data]

    async def get_portfolio_metrics(
        self, account_id: int, correlation_id: str
    ) -> PortfolioMetrics:
        url = DatabaseEndpoints.PORTFOLIO_METRICS.format(account_id=account_id)
        response_data = await self._get(url, correlation_id)
        standard_resp = self.validate_standard_response(response_data)
        return PortfolioMetrics(**standard_resp.data)

    async def get_price_history(
        self, symbol: str, correlation_id: str
    ) -> List[PricePoint]:
        url = DatabaseEndpoints.PRICE_HISTORY.format(symbol=symbol)
        response_data = await self._get(url, correlation_id)
        standard_resp = self.validate_standard_response(response_data)
        return [PricePoint(**p) for p in standard_resp.data]

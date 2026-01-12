import os
from typing import List

from .models import (
    AccountBalance,
    Position,
    Order,
    CreateOrderBody,
    CreateOrderResponse,
    Trade,
    PortfolioMetrics,
    PricePoint
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

    async def get_account_balance(
        self, account_id: int, correlation_id: str
    ) -> AccountBalance:
        response_data = await self._get(f"/accounts/{account_id}/balance", correlation_id)
        return AccountBalance(**response_data)

    async def get_positions(self, account_id: int, correlation_id: str) -> List[Position]:
        response_data = await self._get(f"/accounts/{account_id}/positions", correlation_id)
        return [Position(**p) for p in response_data]

    async def create_order(
        self, account_id: int, order_body: CreateOrderBody, correlation_id: str
    ) -> CreateOrderResponse:
        order_payload = order_body.model_dump()

        response_data = await self._post(
            f"/accounts/{account_id}/orders",
            correlation_id,
            json_data=order_payload,
        )
        return CreateOrderResponse(**response_data)

    async def execute_order(self, order_id: int, correlation_id: str) -> Order:
        response_data = await self._post(f"/orders/{order_id}/execute", correlation_id, json_data={})
        return Order(**response_data)

    async def get_trade_history(
        self, account_id: int, correlation_id: str
    ) -> List[Trade]:
        response_data = await self._get(f"/accounts/{account_id}/trade_history", correlation_id)
        return [Trade(**t) for t in response_data]

    async def get_portfolio_metrics(
        self, account_id: int, correlation_id: str
    ) -> PortfolioMetrics:
        response_data = await self._get(f"/accounts/{account_id}/portfolio_metrics", correlation_id)
        return PortfolioMetrics(**response_data)

    async def get_price_history(
        self, symbol: str, correlation_id: str
    ) -> List[PricePoint]:
        response_data = await self._get(f"/prices/{symbol}", correlation_id)
        return [PricePoint(**p) for p in response_data]

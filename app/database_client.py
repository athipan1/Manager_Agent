import os
import uuid
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
        super().__init__(base_url=DATABASE_AGENT_URL)
        # ดึง API Key จาก Environment Variable
        self._api_key = os.getenv("DATABASE_AGENT_API_KEY")

    async def _get(self, url: str, correlation_id: str, **kwargs) -> dict:
        headers = kwargs.pop("headers", {})
        # ใส่ API Key และ Correlation ID ใน Header มาตรฐาน
        if self._api_key:
            headers["X-API-KEY"] = self._api_key
        headers["X-Correlation-ID"] = correlation_id
        
        return await super()._get(url, correlation_id, headers=headers, **kwargs)

    async def _post(self, url: str, correlation_id: str, json_data: dict, **kwargs) -> dict:
        headers = kwargs.pop("headers", {})
        if self._api_key:
            headers["X-API-KEY"] = self._api_key
        headers["X-Correlation-ID"] = correlation_id
        
        return await super()._post(url, correlation_id, json_data, headers=headers, **kwargs)

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
        # 1. แปลง Model เป็น Dictionary โดยตรง
        order_payload = order_body.model_dump()

        # 2. แก้ไข: ไม่ต้อง pop('order_type') เพื่อเปลี่ยนเป็น 'side' อีกแล้ว
        # ส่ง order_type ไปตรงๆ ตามที่ Database_Agent คาดหวัง
        
        # 3. (แนะนำเพิ่ม) ใส่ client_order_id หากใน model ไม่มี เพื่อป้องกันออเดอร์ซ้ำ (Idempotency)
        if not order_payload.get('client_order_id'):
            order_payload['client_order_id'] = str(uuid.uuid4())

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

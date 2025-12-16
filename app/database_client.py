import httpx
from typing import List, Optional, Dict, Any

from .models import AccountBalance, Position, Order, CreateOrderBody, CreateOrderResponse
from .config import DATABASE_AGENT_URL
from .logger import report_logger

# Default account ID for simplicity
ACCOUNT_ID = 1

async def get_account_balance() -> Optional[AccountBalance]:
    """Retrieves the cash balance for the default account."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{DATABASE_AGENT_URL}/accounts/{ACCOUNT_ID}/balance", timeout=5.0)
            response.raise_for_status()
            return AccountBalance(**response.json())
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            report_logger.error(f"Error fetching account balance: {e}")
            return None

async def get_positions() -> List[Position]:
    """Retrieves all positions for the default account."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(f"{DATABASE_AGENT_URL}/accounts/{ACCOUNT_ID}/positions", timeout=5.0)
            response.raise_for_status()
            data = response.json()
            return [Position(**p) for p in data]
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            report_logger.error(f"Error fetching positions: {e}")
            return []

async def create_order(order_body: CreateOrderBody) -> Optional[CreateOrderResponse]:
    """Creates a new order."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{DATABASE_AGENT_URL}/accounts/{ACCOUNT_ID}/orders",
                json=order_body.model_dump(),
                timeout=5.0
            )
            response.raise_for_status()
            return CreateOrderResponse(**response.json())
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            report_logger.error(f"Error creating order: {e}")
            return None

async def execute_order(order_id: int) -> Optional[Order]:
    """Executes a pending order."""
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(f"{DATABASE_AGENT_URL}/orders/{order_id}/execute", timeout=5.0)
            response.raise_for_status()
            return Order(**response.json())
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            report_logger.error(f"Error executing order: {e}")
            return None

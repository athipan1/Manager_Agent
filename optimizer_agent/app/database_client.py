import httpx
from .models import TradeHistory, PortfolioMetrics
import os

DATABASE_AGENT_URL = os.getenv("DATABASE_AGENT_URL", "http://database-agent:8003")

class DatabaseClient:
    async def get_trade_history(self) -> TradeHistory:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{DATABASE_AGENT_URL}/trades")
            response.raise_for_status()
            return TradeHistory(**response.json())

    async def get_portfolio_metrics(self) -> PortfolioMetrics:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{DATABASE_AGENT_URL}/metrics")
            response.raise_for_status()
            return PortfolioMetrics(**response.json())

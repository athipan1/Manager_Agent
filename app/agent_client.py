import httpx
import asyncio
from typing import Tuple, Dict, Any

from .models import AgentRequestBody
from .config import TECHNICAL_AGENT_URL, FUNDAMENTAL_AGENT_URL, DATABASE_AGENT_URL

async def _call_agent(client: httpx.AsyncClient, url: str, request_body: Dict) -> Dict[str, Any]:
    """Helper function to make a single API call to an agent."""
    try:
        response = await client.post(url, json=request_body, timeout=10.0)
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
        return response.json()
    except httpx.RequestError as exc:
        # Handle connection errors, timeouts, etc.
        return {"error": f"An error occurred while requesting {exc.request.url!r}: {exc}"}
    except httpx.HTTPStatusError as exc:
        # Handle non-xx responses
        return {"error": f"Error response {exc.response.status_code} while requesting {exc.request.url!r}."}

async def call_agents(ticker: str) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """
    Calls the Technical, Fundamental, and Database agents concurrently.
    """
    request_body = AgentRequestBody(ticker=ticker).model_dump()

    async with httpx.AsyncClient() as client:
        technical_task = _call_agent(client, TECHNICAL_AGENT_URL, request_body)
        fundamental_task = _call_agent(client, FUNDAMENTAL_AGENT_URL, request_body)
        database_task = _call_agent(client, DATABASE_AGENT_URL, request_body)

        results = await asyncio.gather(
            technical_task,
            fundamental_task,
            database_task,
            return_exceptions=True  # Prevent one failed request from stopping the other
        )

    return results[0], results[1], results[2]

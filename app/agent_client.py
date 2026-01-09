import asyncio
from typing import Tuple, Dict, Any

from .models import AgentRequestBody
from .config import TECHNICAL_AGENT_URL, FUNDAMENTAL_AGENT_URL
from .resilient_client import ResilientAgentClient, AgentUnavailable

async def call_agents(ticker: str, correlation_id: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    Calls both the Technical and Fundamental agents concurrently using ResilientAgentClient.
    """
    request_body = AgentRequestBody(ticker=ticker).model_dump()

    tech_client = ResilientAgentClient(base_url=TECHNICAL_AGENT_URL)
    fund_client = ResilientAgentClient(base_url=FUNDAMENTAL_AGENT_URL)

    async with tech_client as tc, fund_client as fc:
        technical_task = tc._post("/analyze", correlation_id, request_body)
        fundamental_task = fc._post("/analyze", correlation_id, request_body)

        results = await asyncio.gather(
            technical_task,
            fundamental_task,
            return_exceptions=True  # Prevent one failed request from stopping the other
        )

    # Handle potential AgentUnavailable exceptions from ResilientAgentClient
    tech_response = results[0] if not isinstance(results[0], BaseException) else {"error": str(results[0])}
    fund_response = results[1] if not isinstance(results[1], BaseException) else {"error": str(results[1])}


    return tech_response, fund_response

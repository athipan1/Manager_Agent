import asyncio
from typing import Tuple, Dict, Any

from .models import AgentRequestBody
from .config import TECHNICAL_AGENT_URL, FUNDAMENTAL_AGENT_URL
from .resilient_client import ResilientAgentClient, AgentUnavailable
from .contracts import AnalysisEndpoints, StandardAgentResponse

async def call_agents(ticker: str, correlation_id: str) -> Tuple[StandardAgentResponse | Dict[str, Any], StandardAgentResponse | Dict[str, Any]]:
    """
    Calls both the Technical and Fundamental agents concurrently using ResilientAgentClient.
    """
    request_body = AgentRequestBody(ticker=ticker).model_dump()

    tech_client = ResilientAgentClient(base_url=TECHNICAL_AGENT_URL)
    fund_client = ResilientAgentClient(base_url=FUNDAMENTAL_AGENT_URL)

    async with tech_client as tc, fund_client as fc:
        technical_task = tc._post(AnalysisEndpoints.ANALYZE, correlation_id, request_body)
        fundamental_task = fc._post(AnalysisEndpoints.ANALYZE, correlation_id, request_body)

        results = await asyncio.gather(
            technical_task,
            fundamental_task,
            return_exceptions=True
        )

    # Handle responses and validate them
    def process_result(result, client: ResilientAgentClient):
        if isinstance(result, BaseException):
            return {"status": "error", "error": {"message": str(result)}}
        try:
            return client.validate_standard_response(result)
        except Exception as e:
            return {"status": "error", "error": {"message": str(e)}}

    tech_response = process_result(results[0], tech_client)
    fund_response = process_result(results[1], fund_client)

    return tech_response, fund_response

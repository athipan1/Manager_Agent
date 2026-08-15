import asyncio
from typing import Tuple, Dict, Any, Optional

from .models import AgentRequestBody
from .config import TECHNICAL_AGENT_URL, FUNDAMENTAL_AGENT_URL
from .resilient_client import ResilientAgentClient
from .contracts import AnalysisEndpoints, StandardAgentResponse
from .scanner_client import get_scanner_prefetch


DEFAULT_TECHNICAL_TIMEFRAME = "1d"
SUPPORTED_TECHNICAL_TIMEFRAMES = {"1d", "1h", "30m", "15m"}


def build_agent_request_bodies(
    ticker: str,
    *,
    technical_timeframe: str = DEFAULT_TECHNICAL_TIMEFRAME,
    fundamental_context: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Build agent-specific request payloads without cross-agent contract drift.

    Technical_Agent owns candle timeframe semantics, so Manager sends an
    explicit ``timeframe`` field rather than relying on its default or reusing
    the Fundamental ``period`` field. Fundamental_Agent keeps the legacy
    Manager request body and optional Scanner-prefetched context.
    """

    timeframe = str(technical_timeframe or "").strip().lower()
    if timeframe not in SUPPORTED_TECHNICAL_TIMEFRAMES:
        supported = ", ".join(sorted(SUPPORTED_TECHNICAL_TIMEFRAMES))
        raise ValueError(
            f"Unsupported technical timeframe '{technical_timeframe}'. "
            f"Supported values: {supported}."
        )

    request_body = AgentRequestBody(ticker=ticker).model_dump()
    technical_body = {
        "ticker": request_body["ticker"],
        "timeframe": timeframe,
    }

    fundamental_body = dict(request_body)
    context = fundamental_context or get_scanner_prefetch(ticker)
    if context:
        fundamental_body["prefetched_data"] = context

    return technical_body, fundamental_body


async def call_agents(
    ticker: str,
    correlation_id: str,
    fundamental_context: Optional[Dict[str, Any]] = None,
    technical_timeframe: str = DEFAULT_TECHNICAL_TIMEFRAME,
) -> Tuple[StandardAgentResponse | Dict[str, Any], StandardAgentResponse | Dict[str, Any]]:
    technical_body, fundamental_body = build_agent_request_bodies(
        ticker,
        technical_timeframe=technical_timeframe,
        fundamental_context=fundamental_context,
    )

    tech_client = ResilientAgentClient(base_url=TECHNICAL_AGENT_URL)
    fund_client = ResilientAgentClient(base_url=FUNDAMENTAL_AGENT_URL)

    async with tech_client as tc, fund_client as fc:
        technical_task = tc._post(
            AnalysisEndpoints.ANALYZE,
            correlation_id,
            technical_body,
        )
        fundamental_task = fc._post(
            AnalysisEndpoints.ANALYZE,
            correlation_id,
            fundamental_body,
        )

        results = await asyncio.gather(
            technical_task,
            fundamental_task,
            return_exceptions=True,
        )

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

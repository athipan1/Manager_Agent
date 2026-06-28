"""System routes for Manager_Agent.

This module moves low-risk operational endpoints out of the legacy monolithic
`app.main` route surface and into a modular router.
"""

from __future__ import annotations

import datetime
import uuid
from typing import Union

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from .. import config
from ..backtest_agent_client import BacktestAgentClient
from ..config_manager import config_manager
from ..contracts import StandardAgentResponse
from ..database_client import DatabaseAgentClient
from ..logger import report_logger
from ..risk_agent_client import check_risk_agent_health_async
from ..stock_preflight import run_stock_live_preflight
from ..workflows.single_analysis_workflow import manager_metadata

router = APIRouter()


def utc_now() -> datetime.datetime:
    """Return current UTC timestamp."""
    return datetime.datetime.now(datetime.UTC)


@router.get("/preflight/live", response_model=StandardAgentResponse)
async def stock_live_preflight(account_id: Union[int, str] = None, sample_symbol: str = "AAPL"):
    """Run stock live preflight checks."""
    correlation_id = str(uuid.uuid4())
    resolved_account_id = account_id if account_id is not None else config_manager.get("DEFAULT_ACCOUNT_ID")
    result = await run_stock_live_preflight(resolved_account_id, sample_symbol, correlation_id)
    return StandardAgentResponse(
        status="success" if result["approved"] else "error",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=utc_now(),
        data=result,
        metadata=manager_metadata(
            risk_context_loaded=result["checks"].get("database", {}).get("status") == "pass"
        ),
    )


@router.get("/health", response_model=StandardAgentResponse)
async def health_check():
    """Check Manager_Agent downstream dependency health."""
    is_healthy = True
    correlation_id = str(uuid.uuid4())
    downstream_services = {
        "database_agent": {"status": "healthy", "details": "Connected successfully."},
        "risk_agent": {"status": "healthy", "details": "Connected successfully."},
        "backtest_agent": {
            "status": "disabled" if not config.BACKTEST_AGENT_ENABLED else "healthy",
            "details": "Backtest integration disabled." if not config.BACKTEST_AGENT_ENABLED else "Connected successfully.",
        },
    }

    try:
        async with DatabaseAgentClient() as db_client:
            await db_client.health(correlation_id=correlation_id)
    except Exception as exc:
        is_healthy = False
        downstream_services["database_agent"] = {"status": "unhealthy", "details": f"Connection failed: {str(exc)}"}
        report_logger.warning(f"Health check failed: Database Agent connection error: {exc}")

    try:
        risk_health = await check_risk_agent_health_async(correlation_id=correlation_id)
        downstream_services["risk_agent"]["details"] = risk_health
    except Exception as exc:
        is_healthy = False
        downstream_services["risk_agent"] = {"status": "unhealthy", "details": f"Connection failed: {str(exc)}"}
        report_logger.warning(f"Health check failed: Risk Agent connection error: {exc}")

    if config.BACKTEST_AGENT_ENABLED:
        try:
            async with BacktestAgentClient() as backtest_client:
                downstream_services["backtest_agent"]["details"] = await backtest_client.health(correlation_id)
        except Exception as exc:
            downstream_services["backtest_agent"] = {"status": "unhealthy", "details": f"Connection failed: {str(exc)}"}
            report_logger.warning(f"Advisory health check failed: Backtest Agent connection error: {exc}")

    content = StandardAgentResponse(
        status="success" if is_healthy else "error",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=utc_now(),
        data={"dependencies": downstream_services},
        metadata=manager_metadata(risk_context_loaded=downstream_services["database_agent"]["status"] == "healthy"),
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        content=content.model_dump(mode="json"),
    )
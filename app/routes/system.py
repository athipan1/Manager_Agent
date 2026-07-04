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

MANAGER_AGENT_TYPE = "manager-agent"
MANAGER_VERSION = "1.0.0"
SCHEMA_VERSION = "1.0"


def utc_now() -> datetime.datetime:
    """Return current UTC timestamp."""
    return datetime.datetime.now(datetime.UTC)


def configured_dry_run() -> bool:
    """Return the configured dry-run flag with a safe default for older configs."""
    return bool(getattr(config, "DRY_RUN", True))


def build_system_response(
    *,
    status_value: str,
    data: dict,
    correlation_id: str,
    metadata: dict | None = None,
    error: dict | None = None,
) -> StandardAgentResponse:
    """Build a standard Manager system response."""
    return StandardAgentResponse(
        status=status_value,
        agent_type=MANAGER_AGENT_TYPE,
        version=MANAGER_VERSION,
        schema_version=SCHEMA_VERSION,
        timestamp=utc_now(),
        correlation_id=correlation_id,
        data=data,
        metadata=metadata or {},
        error=error,
    )


@router.get("/version", response_model=StandardAgentResponse)
async def version_check():
    """Return Manager_Agent and API contract version metadata."""
    correlation_id = str(uuid.uuid4())
    return build_system_response(
        status_value="success",
        correlation_id=correlation_id,
        data={
            "agent_type": MANAGER_AGENT_TYPE,
            "version": MANAGER_VERSION,
            "schema_version": SCHEMA_VERSION,
            "api_contract": "multi-agent-trading-api-contract",
        },
        metadata={
            "required_operational_endpoints": ["/health", "/ready", "/version"],
        },
    )


@router.get("/ready", response_model=StandardAgentResponse)
async def readiness_check():
    """Check whether Manager_Agent is configured to accept orchestration requests."""
    correlation_id = str(uuid.uuid4())
    readiness = {
        "ready": True,
        "trading_mode": config.TRADING_MODE,
        "trading_enabled": config.TRADING_ENABLED,
        "allow_live_trading": config.ALLOW_LIVE_TRADING,
        "manual_approval_required": config.MANUAL_APPROVAL_REQUIRED,
        "asset_class": config.ASSET_CLASS,
        "dependencies": {
            "technical_agent_url_configured": bool(config.TECHNICAL_AGENT_URL),
            "fundamental_agent_url_configured": bool(config.FUNDAMENTAL_AGENT_URL),
            "database_agent_url_configured": bool(config.DATABASE_AGENT_URL),
            "risk_agent_url_configured": bool(config.RISK_AGENT_URL),
            "execution_agent_url_configured": bool(config.EXECUTION_AGENT_URL),
            "learning_agent_url_configured": bool(config.AUTO_LEARNING_AGENT_URL),
            "scanner_agent_url_configured": bool(config.SCANNER_AGENT_URL),
            "backtest_agent_enabled": config.BACKTEST_AGENT_ENABLED,
        },
    }
    return build_system_response(
        status_value="success",
        correlation_id=correlation_id,
        data=readiness,
        metadata=manager_metadata(dry_run=configured_dry_run()),
    )


@router.get("/preflight/live", response_model=StandardAgentResponse)
async def stock_live_preflight(account_id: Union[int, str] = None, sample_symbol: str = "AAPL"):
    """Run stock live preflight checks."""
    correlation_id = str(uuid.uuid4())
    resolved_account_id = account_id if account_id is not None else config_manager.get("DEFAULT_ACCOUNT_ID")
    result = await run_stock_live_preflight(resolved_account_id, sample_symbol, correlation_id)
    return StandardAgentResponse(
        status="success" if result["approved"] else "error",
        agent_type=MANAGER_AGENT_TYPE,
        version=MANAGER_VERSION,
        schema_version=SCHEMA_VERSION,
        timestamp=utc_now(),
        correlation_id=correlation_id,
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
        agent_type=MANAGER_AGENT_TYPE,
        version=MANAGER_VERSION,
        schema_version=SCHEMA_VERSION,
        timestamp=utc_now(),
        correlation_id=correlation_id,
        data={"dependencies": downstream_services},
        metadata=manager_metadata(risk_context_loaded=downstream_services["database_agent"]["status"] == "healthy"),
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK if is_healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        content=content.model_dump(mode="json"),
    )

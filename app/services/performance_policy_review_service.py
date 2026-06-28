"""Best-effort Performance -> Learning -> Curator policy review orchestration.

This service does not apply policy changes. It only gathers recommendations and
persists them as advisory audit metadata for human review.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from .. import config
from ..config_manager import config_manager
from ..database_client import DatabaseAgentClient
from ..logger import report_logger
from ..resilient_client import ResilientAgentClient
from .serialization_service import jsonable

PERFORMANCE_DATABASE_SUMMARY_ENDPOINT = "/performance/trade-plans/database-summary"
LEARNING_PERFORMANCE_ENDPOINT = "/learn/performance"
CURATOR_PERFORMANCE_POLICY_ENDPOINT = "/curate/performance-policy"


def current_policy_snapshot() -> Dict[str, Any]:
    """Return the current Manager policy snapshot sent to Learning/Curator."""
    return {
        "agent_weights": config_manager.get("AGENT_WEIGHTS"),
        "risk": {
            "risk_per_trade": config_manager.get("RISK_PER_TRADE"),
            "max_position_pct": config_manager.get("MAX_POSITION_PERCENTAGE"),
            "stop_loss_pct": config_manager.get("STOP_LOSS_PERCENTAGE"),
        },
        "asset_biases": config_manager.get("ASSET_BIASES", {}),
        "strategy_bias": {
            "preferred_regime": config_manager.get("PREFERRED_REGIME") or "neutral",
        },
    }


def performance_summary_params(
    *,
    account_id: Union[int, str],
    symbol: Optional[str],
    initial_equity: float,
    period: str = "30d",
    status: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """Build query params for Performance_Agent database-backed TradePlan summary."""
    params: Dict[str, Any] = {
        "initial_equity": initial_equity,
        "period": period,
        "account_id": str(account_id),
        "limit": limit,
        "include_fills": True,
    }
    if symbol:
        params["symbol"] = symbol.upper()
    if status:
        params["status"] = status
    return params


def learning_payload(
    *,
    account_id: Union[int, str],
    performance_summary: Dict[str, Any],
    current_policy: Optional[Dict[str, Any]] = None,
    min_closed_plans: int = 5,
) -> Dict[str, Any]:
    """Build Learning_Agent /learn/performance payload."""
    return {
        "account_id": str(account_id),
        "learning_mode": "performance_summary_review",
        "performance_summary": performance_summary,
        "current_policy": current_policy or current_policy_snapshot(),
        "min_closed_plans": min_closed_plans,
    }


def curator_payload(
    *,
    account_id: Union[int, str],
    learning_result: Dict[str, Any],
    current_policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build Curator_Agent /curate/performance-policy payload."""
    return {
        "account_id": str(account_id),
        "learning_result": learning_result,
        "current_policy": current_policy or current_policy_snapshot(),
    }


async def _get_performance_summary(
    *,
    account_id: Union[int, str],
    symbol: Optional[str],
    initial_equity: float,
    period: str,
    correlation_id: str,
) -> Dict[str, Any]:
    async with ResilientAgentClient(
        base_url=config.PERFORMANCE_AGENT_URL,
        timeout=config.PERFORMANCE_AGENT_TIMEOUT,
    ) as client:
        response = await client._get(
            PERFORMANCE_DATABASE_SUMMARY_ENDPOINT,
            correlation_id,
            params=performance_summary_params(
                account_id=account_id,
                symbol=symbol,
                initial_equity=initial_equity,
                period=period,
            ),
        )
        standard_response = client.validate_standard_response(response)
        return standard_response.data or {}


async def _learn_from_summary(
    *,
    account_id: Union[int, str],
    performance_summary: Dict[str, Any],
    correlation_id: str,
) -> Dict[str, Any]:
    payload = learning_payload(
        account_id=account_id,
        performance_summary=performance_summary,
    )
    async with ResilientAgentClient(base_url=config.AUTO_LEARNING_AGENT_URL) as client:
        response = await client._post(
            LEARNING_PERFORMANCE_ENDPOINT,
            correlation_id,
            json_data=payload,
        )
        standard_response = client.validate_standard_response(response)
        return standard_response.data or {}


async def _curate_learning_result(
    *,
    account_id: Union[int, str],
    learning_result: Dict[str, Any],
    correlation_id: str,
) -> Dict[str, Any]:
    payload = curator_payload(
        account_id=account_id,
        learning_result=learning_result,
    )
    async with ResilientAgentClient(
        base_url=config.CURATOR_AGENT_URL,
        timeout=config.CURATOR_AGENT_TIMEOUT,
    ) as client:
        response = await client._post(
            CURATOR_PERFORMANCE_POLICY_ENDPOINT,
            correlation_id,
            json_data=payload,
        )
        standard_response = client.validate_standard_response(response)
        return standard_response.data or {}


async def persist_policy_review_signal(
    *,
    db_client: Optional[DatabaseAgentClient],
    account_id: Union[int, str],
    symbol: Optional[str],
    correlation_id: str,
    policy_review: Dict[str, Any],
) -> None:
    """Persist advisory policy review metadata without blocking the main workflow."""
    if db_client is None:
        return
    try:
        await db_client.save_signal(
            account_id=account_id,
            symbol=symbol or "POLICY_REVIEW",
            correlation_id=correlation_id,
            final_verdict="policy_review",
            metadata={
                "flow": "performance_policy_review",
                "policy_review": jsonable(policy_review),
                "auto_apply": False,
                "advisory_only": True,
            },
        )
    except Exception as exc:
        report_logger.warning(
            f"Failed to persist performance policy review signal: {exc}, correlation_id={correlation_id}"
        )


async def run_performance_policy_review(
    *,
    db_client: Optional[DatabaseAgentClient],
    account_id: Union[int, str],
    symbol: Optional[str],
    initial_equity: float,
    correlation_id: str,
    period: str = "30d",
) -> Dict[str, Any]:
    """Run Performance -> Learning -> Curator review as advisory-only best effort."""
    if not config.POLICY_REVIEW_FLOW_ENABLED:
        return {"status": "skipped", "reason": "POLICY_REVIEW_FLOW_ENABLED is false"}

    try:
        performance_summary = await _get_performance_summary(
            account_id=account_id,
            symbol=symbol,
            initial_equity=initial_equity,
            period=period,
            correlation_id=correlation_id,
        )
        learning_result = await _learn_from_summary(
            account_id=account_id,
            performance_summary=performance_summary,
            correlation_id=correlation_id,
        )
        curated_policy = await _curate_learning_result(
            account_id=account_id,
            learning_result=learning_result,
            correlation_id=correlation_id,
        )
        result = {
            "status": "success",
            "advisory_only": True,
            "auto_apply": False,
            "performance_summary": performance_summary,
            "learning_result": learning_result,
            "curated_policy": curated_policy,
        }
        await persist_policy_review_signal(
            db_client=db_client,
            account_id=account_id,
            symbol=symbol,
            correlation_id=correlation_id,
            policy_review=result,
        )
        return result
    except Exception as exc:
        report_logger.warning(
            f"Performance policy review failed: {exc}, correlation_id={correlation_id}"
        )
        return {"status": "skipped", "reason": str(exc), "advisory_only": True, "auto_apply": False}

"""Learning workflow helpers for Manager_Agent.

This module owns Manager-side handling of Learning_Agent responses and policy
updates. It keeps auto-application of learning deltas behind the existing
`APPLY_LEARNING_DELTAS` safety flag.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Union

from .. import config
from ..config_manager import config_manager
from ..database_client import DatabaseAgentClient
from ..learning_client import LearningAgentClient
from ..logger import report_logger


def apply_learning_deltas_if_allowed(learning_response: Any) -> Dict[str, Any]:
    """Apply learning policy deltas only when explicitly enabled.

    This mirrors the legacy Manager behavior:

    - no response / warmup -> no active delta
    - empty delta -> no-op
    - `APPLY_LEARNING_DELTAS=false` -> mark delta as pending approval
    - `APPLY_LEARNING_DELTAS=true` -> apply via config manager
    """
    if not learning_response or learning_response.learning_state == "warmup":
        return {"applied": False, "pending": False, "reason": "no_active_learning_delta"}

    deltas = learning_response.policy_deltas.model_dump(exclude_none=True)
    if not deltas:
        return {"applied": False, "pending": False, "reason": "empty_learning_delta"}

    if not config.APPLY_LEARNING_DELTAS:
        report_logger.warning(
            "Learning policy deltas generated but not applied because APPLY_LEARNING_DELTAS=false."
        )
        return {"applied": False, "pending": True, "reason": "approval_required"}

    config_manager.apply_deltas(deltas)
    return {"applied": True, "pending": False, "reason": None}


async def trigger_learning_cycle_if_allowed(
    *,
    db_client: DatabaseAgentClient,
    account_id: Union[int, str],
    symbol: str,
    correlation_id: str,
    execution_result: Optional[Dict[str, Any]],
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Trigger Learning_Agent unless this is a dry run, then handle deltas."""
    if dry_run:
        return {"applied": False, "pending": False, "reason": "dry_run"}

    learning_client = LearningAgentClient(db_client=db_client)
    learning_response = await learning_client.trigger_learning_cycle(
        account_id=account_id,
        symbol=symbol,
        correlation_id=correlation_id,
        execution_result=execution_result,
    )
    return apply_learning_deltas_if_allowed(learning_response)


def most_impactful_approved_trade(trade_decisions: list[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Return the approved trade with the highest risk amount."""
    approved = [row for row in trade_decisions if row.get("approved")]
    if not approved:
        return None
    return max(approved, key=lambda row: row.get("risk_amount", 0))

"""Database_Agent promotion API adapter for Manager-owned authority.

The shared DatabaseAgentClient keeps the normal X-API-KEY header. This adapter
adds X-PROMOTION-APPROVAL-KEY only to the one privileged transition request,
so the approval credential cannot leak into routine account, order, or context
calls.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional, Union
from urllib.parse import quote

from pydantic import BaseModel


class PromotionAuthorityError(RuntimeError):
    pass


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if hasattr(value, "model_dump"):
        result = value.model_dump(mode="json")
        return result if isinstance(result, dict) else {}
    return {}


class PromotionDatabaseAdapter:
    def __init__(self, db_client: Any) -> None:
        self._db_client = db_client

    async def get_latest_exact(
        self,
        *,
        account_id: Union[int, str],
        symbol: str,
        strategy_id: str,
        timeframe: str,
        correlation_id: str,
        max_age_hours: Optional[float] = None,
        validation_profile: str = "nested_walk_forward_v2",
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "account_id": str(account_id),
            "symbol": symbol.upper(),
            "strategy_id": strategy_id,
            "timeframe": timeframe,
            "validation_profile": validation_profile,
        }
        if max_age_hours is not None and max_age_hours > 0:
            params["max_age_hours"] = max(1, int(max_age_hours))
        response_data = await self._db_client._get(
            "/backtests/promotions/latest/exact",
            correlation_id,
            params=params,
        )
        standard = self._db_client.validate_standard_response(response_data)
        promotion = _as_dict(standard.data)
        if not promotion:
            raise PromotionAuthorityError(
                "Database_Agent returned no exact promotion data"
            )
        return promotion

    async def approve_for_paper(
        self,
        promotion: Dict[str, Any],
        *,
        correlation_id: str,
    ) -> Dict[str, Any]:
        token = os.getenv("BACKTEST_PROMOTION_APPROVAL_TOKEN", "").strip()
        if not token:
            raise PromotionAuthorityError(
                "BACKTEST_PROMOTION_APPROVAL_TOKEN is required for Manager approval"
            )
        promotion_id = str(promotion.get("promotion_id") or "")
        run_id = str(promotion.get("run_id") or "")
        state = str(promotion.get("state") or "")
        version = promotion.get("version")
        evidence_version = promotion.get("evidence_version")
        if not promotion_id or not run_id:
            raise PromotionAuthorityError("promotion identity is incomplete")
        if state != "ROBUSTNESS_PASSED":
            raise PromotionAuthorityError(
                f"paper approval requires ROBUSTNESS_PASSED, got {state or 'missing'}"
            )
        if not isinstance(version, int) or version < 1:
            raise PromotionAuthorityError("promotion version is invalid")
        if not isinstance(evidence_version, int) or evidence_version < 1:
            raise PromotionAuthorityError("promotion evidence_version is invalid")

        encoded_promotion_id = quote(promotion_id, safe="")
        payload = {
            "expected_state": "ROBUSTNESS_PASSED",
            "expected_version": version,
            "next_state": "APPROVED_FOR_PAPER",
            "reason_code": "manager_paper_approval",
            "reason": (
                "Manager_Agent approved exact immutable Backtest evidence for "
                "paper-only risk evaluation and execution."
            ),
            "evidence_run_id": run_id,
            "correlation_id": correlation_id,
            "evidence_version": evidence_version,
            "approver": os.getenv(
                "BACKTEST_PROMOTION_APPROVER",
                "manager-agent",
            ).strip()
            or "manager-agent",
            "metadata": {
                "authority": "manager-agent",
                "trading_mode": "PAPER",
                "requires_risk_approval": True,
                "execution_agent_only_broker_boundary": True,
            },
        }
        response_data = await self._db_client._post(
            f"/backtests/promotions/{encoded_promotion_id}/transition",
            correlation_id,
            json_data=payload,
            extra_headers={"X-PROMOTION-APPROVAL-KEY": token},
        )
        standard = self._db_client.validate_standard_response(response_data)
        approved = _as_dict(standard.data)
        if approved.get("state") != "APPROVED_FOR_PAPER":
            raise PromotionAuthorityError(
                "Database_Agent did not return APPROVED_FOR_PAPER"
            )
        return approved

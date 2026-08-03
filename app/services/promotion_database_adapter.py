"""Database_Agent promotion API adapter for Manager-owned authority.

The shared DatabaseAgentClient keeps the normal X-API-KEY header. This adapter
adds X-PROMOTION-APPROVAL-KEY only to privileged promotion transitions and
paper-observation writes, so the credential cannot leak into routine account,
order, or context calls.
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


def _approval_token() -> str:
    token = os.getenv("BACKTEST_PROMOTION_APPROVAL_TOKEN", "").strip()
    if not token:
        raise PromotionAuthorityError(
            "BACKTEST_PROMOTION_APPROVAL_TOKEN is required for privileged "
            "promotion operations"
        )
    return token


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
        token = _approval_token()
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

    async def observe_for_paper(
        self,
        *,
        promotion_id: str,
        expected_state: str,
        expected_version: int,
        observation_key: str,
        observed_at: str,
        paper_drawdown_pct: float,
        reconciliation_ok: bool,
        duplicate_order_count: int,
        broker_order_count: int,
        database_order_count: int,
        filled_order_count: int,
        strategy_drift: bool,
        emergency_halt: bool,
        correlation_id: str,
        notes: Optional[list[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        token = _approval_token()
        if expected_state not in {"APPROVED_FOR_PAPER", "PAPER_OBSERVING"}:
            raise PromotionAuthorityError(
                "paper observation requires an approved or observing promotion"
            )
        if not promotion_id or expected_version < 1 or not observation_key:
            raise PromotionAuthorityError("paper observation identity is incomplete")

        encoded_promotion_id = quote(promotion_id, safe="")
        payload = {
            "expected_state": expected_state,
            "expected_version": expected_version,
            "observation_key": observation_key,
            "observed_at": observed_at,
            "paper_drawdown_pct": paper_drawdown_pct,
            "reconciliation_ok": reconciliation_ok,
            "duplicate_order_count": duplicate_order_count,
            "broker_order_count": broker_order_count,
            "database_order_count": database_order_count,
            "filled_order_count": filled_order_count,
            "strategy_drift": strategy_drift,
            "emergency_halt": emergency_halt,
            "notes": notes or [],
            "correlation_id": correlation_id,
            "metadata": {
                "authority": "manager-agent",
                "trading_mode": "PAPER",
                "requires_risk_approval": True,
                "execution_agent_only_broker_boundary": True,
                **(metadata or {}),
            },
        }
        response_data = await self._db_client._post(
            f"/backtests/promotion-observations/{encoded_promotion_id}",
            correlation_id,
            json_data=payload,
            extra_headers={"X-PROMOTION-APPROVAL-KEY": token},
        )
        standard = self._db_client.validate_standard_response(response_data)
        observation = _as_dict(standard.data)
        if observation.get("promotion_id") != promotion_id:
            raise PromotionAuthorityError(
                "Database_Agent returned the wrong observed promotion"
            )
        if observation.get("observation_key") != observation_key:
            raise PromotionAuthorityError(
                "Database_Agent returned the wrong observation identity"
            )
        if observation.get("to_state") not in {
            "PAPER_OBSERVING",
            "EXPIRED",
            "REVOKED",
        }:
            raise PromotionAuthorityError(
                "Database_Agent returned an invalid observation state"
            )
        if not isinstance(observation.get("to_version"), int):
            raise PromotionAuthorityError(
                "Database_Agent returned an invalid observation version"
            )
        return observation

    async def list_observations(
        self,
        *,
        promotion_id: str,
        correlation_id: str,
    ) -> list[Dict[str, Any]]:
        encoded_promotion_id = quote(promotion_id, safe="")
        response_data = await self._db_client._get(
            f"/backtests/promotion-observations/{encoded_promotion_id}",
            correlation_id,
        )
        standard = self._db_client.validate_standard_response(response_data)
        data = standard.data
        if not isinstance(data, list):
            raise PromotionAuthorityError(
                "Database_Agent returned an invalid observation ledger"
            )
        return [_as_dict(row) for row in data]

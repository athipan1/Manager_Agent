"""Promotion-authority execution gate for Manager_Agent.

Raw Backtest records remain diagnostic evidence. Database_Agent's latest exact
promotion is the execution authority. Manager_Agent may approve an exact
ROBUSTNESS_PASSED promotion only when explicit paper-approval policy is enabled;
Risk_Agent approval remains mandatory downstream and only Execution_Agent may
contact a trading broker.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Union

from .. import config
from .promotion_database_adapter import PromotionDatabaseAdapter


APPROVED_STATES = {"APPROVED_FOR_PAPER", "PAPER_OBSERVING"}
TERMINAL_STATES = {"REJECTED", "FAILED", "EXPIRED", "REVOKED"}
PRE_APPROVAL_STATES = {"GENERATED", "VALIDATED", "OOS_PASSED"}
VALIDATION_PROFILE = "nested_walk_forward_v2"


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _symbol(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("ticker") or value.get("symbol") or "").upper()
    return str(
        getattr(value, "ticker", None)
        or getattr(value, "symbol", None)
        or ""
    ).upper()


def _parse_timestamp(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _promotion_timestamp(promotion: Dict[str, Any]) -> datetime:
    return _parse_timestamp(
        promotion.get("updated_at") or promotion.get("created_at")
    ) or datetime.min.replace(tzinfo=timezone.utc)


def _strategy_ids(
    primary_strategy_id: str,
    strategy_ids: Optional[Iterable[str]],
) -> List[str]:
    values = (
        strategy_ids
        if strategy_ids is not None
        else (
            config.BACKTEST_GATE_STRATEGY_IDS
            if config.BACKTEST_MULTI_STRATEGY_GATE_ENABLED
            else (primary_strategy_id,)
        )
    )
    resolved = list(
        dict.fromkeys(
            str(value).strip() for value in values if str(value).strip()
        )
    )
    return resolved or [primary_strategy_id]


def _resolve_account_id(
    account_id: Optional[Union[int, str]],
    selected_positions: List[Dict[str, Any]],
) -> str:
    if account_id is not None and str(account_id).strip():
        return str(account_id).strip()
    position_accounts = {
        str(row.get("account_id")).strip()
        for row in selected_positions
        if isinstance(row, dict) and row.get("account_id") is not None
    }
    if len(position_accounts) == 1:
        return next(iter(position_accounts))
    return str(config.DEFAULT_ACCOUNT_ID)


def _decision(
    *,
    promotion: Dict[str, Any],
    lookup_error: Optional[str],
    account_id: str,
    symbol: str,
    skill_id: str,
    strategy_id: str,
    timeframe: str,
    max_age_hours: float,
    now: datetime,
    auto_approve: bool,
) -> Dict[str, Any]:
    reasons: List[str] = []
    state = str(promotion.get("state") or "")
    promotion_id = str(promotion.get("promotion_id") or "")
    run_id = str(promotion.get("run_id") or "")

    if lookup_error:
        reasons.append("backtest_promotion_lookup_failed")
    if not promotion:
        reasons.append("backtest_promotion_not_found")
    if promotion:
        expected = {
            "account_id": account_id,
            "skill_id": skill_id,
            "strategy_id": strategy_id,
            "symbol": symbol,
            "timeframe": timeframe,
            "validation_profile": VALIDATION_PROFILE,
        }
        actual = {
            "account_id": str(promotion.get("account_id") or ""),
            "skill_id": str(promotion.get("skill_id") or ""),
            "strategy_id": str(promotion.get("strategy_id") or ""),
            "symbol": str(promotion.get("symbol") or "").upper(),
            "timeframe": str(promotion.get("timeframe") or ""),
            "validation_profile": str(
                promotion.get("validation_profile") or ""
            ),
        }
        for field, expected_value in expected.items():
            if actual[field] != str(expected_value):
                reasons.append(f"backtest_promotion_{field}_mismatch")

        if not promotion_id or not run_id:
            reasons.append("backtest_promotion_identity_missing")
        if not isinstance(promotion.get("version"), int):
            reasons.append("backtest_promotion_version_invalid")
        if not isinstance(promotion.get("evidence_version"), int):
            reasons.append("backtest_promotion_evidence_version_invalid")

        expires_at = _parse_timestamp(promotion.get("expires_at"))
        if expires_at is not None and expires_at <= now:
            reasons.append("backtest_promotion_expired")

        evidence_time = _promotion_timestamp(promotion)
        if evidence_time == datetime.min.replace(tzinfo=timezone.utc):
            reasons.append("backtest_promotion_timestamp_missing")
        elif max_age_hours > 0:
            age_hours = max(0.0, (now - evidence_time).total_seconds() / 3600.0)
            if age_hours > max_age_hours:
                reasons.append("backtest_promotion_stale")

        if state in TERMINAL_STATES:
            reasons.append(f"backtest_promotion_terminal_{state.lower()}")
        elif state in PRE_APPROVAL_STATES:
            reasons.append("backtest_promotion_not_robustness_passed")
        elif state == "ROBUSTNESS_PASSED":
            reasons.append(
                "backtest_promotion_approval_failed"
                if auto_approve
                else "backtest_promotion_approval_required"
            )
        elif state not in APPROVED_STATES:
            reasons.append("backtest_promotion_state_invalid")

    return {
        "symbol": symbol,
        "allowed": not reasons,
        "rejection_codes": sorted(set(reasons)),
        "account_id": account_id,
        "skill_id": skill_id,
        "strategy_id": strategy_id,
        "promotion_id": promotion_id or None,
        "promotion_state": state or None,
        "promotion_version": promotion.get("version"),
        "evidence_version": promotion.get("evidence_version"),
        "latest_run_id": run_id or None,
        "dataset_fingerprint": promotion.get("dataset_fingerprint"),
        "engine_version": promotion.get("engine_version"),
        "validation_profile": promotion.get("validation_profile"),
        "authority": "database-agent-backtest-promotion",
        "requires_risk_approval": True,
        "broker_boundary": "execution-agent-only",
        "mode": "required",
    }


async def filter_candidates_with_promotion_gate(
    *,
    db_client: Any,
    selected_positions: List[Dict[str, Any]],
    position_analysis_payloads: List[Dict[str, Any]],
    correlation_id: str,
    required: bool,
    skill_id: str,
    strategy_id: str,
    timeframe: str,
    max_age_hours: float,
    now: Optional[datetime] = None,
    strategy_ids: Optional[Iterable[str]] = None,
    walk_forward_required: Optional[bool] = None,
    account_id: Optional[Union[int, str]] = None,
    auto_approve: Optional[bool] = None,
) -> Dict[str, Any]:
    del walk_forward_required
    resolved_account_id = _resolve_account_id(account_id, selected_positions)
    resolved_strategy_ids = _strategy_ids(strategy_id, strategy_ids)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    approval_enabled = (
        _env_bool("BACKTEST_PROMOTION_AUTO_APPROVE_PAPER", False)
        if auto_approve is None
        else auto_approve
    )

    symbols = list(
        dict.fromkeys(
            _symbol(position)
            for position in selected_positions
            if _symbol(position)
        )
    )
    if not required:
        disabled_decisions = [
            {
                "symbol": symbol,
                "allowed": True,
                "rejection_codes": [],
                "account_id": resolved_account_id,
                "authority": "disabled",
                "mode": "disabled",
            }
            for symbol in symbols
        ]
        return {
            "status": "disabled",
            "required": False,
            "account_id": resolved_account_id,
            "strategy_ids": resolved_strategy_ids,
            "selected_positions": selected_positions,
            "position_analysis_payloads": position_analysis_payloads,
            "decisions": disabled_decisions,
            "rejected": [],
            "summary": {
                "candidate_count": len(disabled_decisions),
                "allowed_count": len(disabled_decisions),
                "rejected_count": 0,
            },
        }

    adapter = PromotionDatabaseAdapter(db_client)
    promotions: Dict[tuple[str, str], Dict[str, Any]] = {}
    lookup_errors: Dict[tuple[str, str], str] = {}

    async def lookup(symbol: str, candidate_strategy_id: str) -> None:
        key = (symbol, candidate_strategy_id)
        try:
            promotion = await adapter.get_latest_exact(
                account_id=resolved_account_id,
                symbol=symbol,
                strategy_id=candidate_strategy_id,
                timeframe=timeframe,
                correlation_id=correlation_id,
                max_age_hours=max_age_hours,
            )
            if promotion.get("state") == "ROBUSTNESS_PASSED" and approval_enabled:
                try:
                    promotion = await adapter.approve_for_paper(
                        promotion,
                        correlation_id=correlation_id,
                    )
                except Exception:
                    promotion = await adapter.get_latest_exact(
                        account_id=resolved_account_id,
                        symbol=symbol,
                        strategy_id=candidate_strategy_id,
                        timeframe=timeframe,
                        correlation_id=correlation_id,
                        max_age_hours=max_age_hours,
                    )
            promotions[key] = promotion
        except Exception as exc:
            response = getattr(exc, "response", None)
            if getattr(response, "status_code", None) != 404:
                lookup_errors[key] = str(exc)

    await asyncio.gather(
        *(
            lookup(symbol, candidate_strategy_id)
            for symbol in symbols
            for candidate_strategy_id in resolved_strategy_ids
        )
    )

    decisions: List[Dict[str, Any]] = []
    for symbol in symbols:
        attempts = [
            _decision(
                promotion=promotions.get((symbol, candidate_strategy_id), {}),
                lookup_error=lookup_errors.get((symbol, candidate_strategy_id)),
                account_id=resolved_account_id,
                symbol=symbol,
                skill_id=skill_id,
                strategy_id=candidate_strategy_id,
                timeframe=timeframe,
                max_age_hours=max_age_hours,
                now=current,
                auto_approve=approval_enabled,
            )
            for candidate_strategy_id in resolved_strategy_ids
        ]
        allowed = [attempt for attempt in attempts if attempt["allowed"]]
        if allowed:
            selected = max(
                allowed,
                key=lambda item: _promotion_timestamp(
                    promotions.get((symbol, str(item["strategy_id"])), {})
                ),
            )
            decisions.append(
                {
                    **selected,
                    "selected_strategy_id": selected["strategy_id"],
                    "attempted_strategy_ids": resolved_strategy_ids,
                    "strategy_attempts": attempts,
                }
            )
        else:
            decisions.append(
                {
                    "symbol": symbol,
                    "allowed": False,
                    "rejection_codes": sorted(
                        {
                            code
                            for attempt in attempts
                            for code in attempt["rejection_codes"]
                        }
                    ),
                    "account_id": resolved_account_id,
                    "selected_strategy_id": None,
                    "attempted_strategy_ids": resolved_strategy_ids,
                    "strategy_attempts": attempts,
                    "authority": "database-agent-backtest-promotion",
                    "mode": "required",
                }
            )

    allowed_symbols = {
        decision["symbol"] for decision in decisions if decision["allowed"]
    }
    allowed_positions = [
        row for row in selected_positions if _symbol(row) in allowed_symbols
    ]
    allowed_payloads = [
        row for row in position_analysis_payloads if _symbol(row) in allowed_symbols
    ]
    rejected = [decision for decision in decisions if not decision["allowed"]]
    return {
        "status": "required",
        "required": True,
        "account_id": resolved_account_id,
        "skill_id": skill_id,
        "strategy_id": (
            resolved_strategy_ids[0] if len(resolved_strategy_ids) == 1 else None
        ),
        "strategy_ids": resolved_strategy_ids,
        "strategy_ids_by_symbol": {
            decision["symbol"]: decision.get("selected_strategy_id")
            for decision in decisions
            if decision.get("selected_strategy_id")
        },
        "timeframe": timeframe,
        "max_age_hours": max_age_hours,
        "authority": "database-agent-backtest-promotion",
        "approval_enabled": approval_enabled,
        "selected_positions": allowed_positions,
        "position_analysis_payloads": allowed_payloads,
        "decisions": decisions,
        "rejected": rejected,
        "summary": {
            "candidate_count": len(decisions),
            "allowed_count": len(decisions) - len(rejected),
            "rejected_count": len(rejected),
        },
    }

"""Execution-aware Scanner opportunity policy for Manager_Agent.

Scanner_Agent may attach ``scanner-opportunity-profile.v1`` inside its existing
``scanner-data-bundle.v1``. Manager treats the profile as advisory evidence and
remains the authority that decides whether a candidate may continue toward
Technical/Fundamental/Backtest/Risk. Present-but-weak or malformed opportunity
evidence fails closed. A temporary compatibility flag controls whether a missing
profile is also blocking while Scanner rollout is coordinated cross-repository.
"""

from __future__ import annotations

import math
import os
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .scanner_candidate_service import candidate_to_dict
from .scanner_data_quality_service import scanner_candidate_data_bundle

SCANNER_OPPORTUNITY_PROFILE_SCHEMA = "scanner-opportunity-profile.v1"
SCANNER_OPPORTUNITY_POLICY_VERSION = "manager-scanner-opportunity-gate.v1"
DEFAULT_MIN_OPPORTUNITY_SCORE = 0.70
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_ALLOWED_STATUSES = frozenset({"qualified", "review", "avoid"})
_ALLOWED_STRATEGY_HINTS = frozenset(
    {"trend_following", "breakout", "mean_reversion"}
)


def _to_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _env_true(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


def scanner_opportunity_profile_required() -> bool:
    return _env_true("SCANNER_OPPORTUNITY_PROFILE_REQUIRED", False)


def scanner_opportunity_live_spread_required() -> bool:
    return _env_true("SCANNER_OPPORTUNITY_REQUIRE_LIVE_SPREAD", False)


def scanner_min_opportunity_score() -> float:
    raw = os.getenv(
        "SCANNER_MIN_OPPORTUNITY_SCORE",
        str(DEFAULT_MIN_OPPORTUNITY_SCORE),
    )
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_MIN_OPPORTUNITY_SCORE
    if not math.isfinite(value):
        return DEFAULT_MIN_OPPORTUNITY_SCORE
    return max(0.0, min(1.0, value))


def _finite_number(value: Any) -> Optional[float]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def scanner_candidate_opportunity_profile(candidate: Any) -> Dict[str, Any]:
    bundle = scanner_candidate_data_bundle(candidate)
    return _to_dict(bundle.get("opportunity_profile"))


def _review_result(
    *,
    symbol: str,
    reason_code: str,
    reason: str,
    profile: Optional[Dict[str, Any]],
    min_score: float,
    profile_required: bool,
    live_spread_required: bool,
) -> Dict[str, Any]:
    profile = profile or {}
    context = _to_dict(profile.get("execution_context"))
    return {
        "symbol": symbol,
        "decision": "REVIEW",
        "allowed": False,
        "reason_code": reason_code,
        "reason": reason,
        "policy_version": SCANNER_OPPORTUNITY_POLICY_VERSION,
        "required_schema": SCANNER_OPPORTUNITY_PROFILE_SCHEMA,
        "schema_version": profile.get("schema_version"),
        "profile_required": profile_required,
        "live_spread_required": live_spread_required,
        "status": profile.get("status"),
        "opportunity_score": _finite_number(profile.get("opportunity_score")),
        "min_opportunity_score": min_score,
        "preferred_strategy_hint": profile.get("preferred_strategy_hint"),
        "execution_context": context,
        "profile_reasons": list(profile.get("reasons") or []),
    }


def evaluate_scanner_candidate_opportunity(
    candidate: Any,
    *,
    min_opportunity_score: Optional[float] = None,
    profile_required: Optional[bool] = None,
    live_spread_required: Optional[bool] = None,
) -> Dict[str, Any]:
    """Return PASS/REVIEW for Scanner execution-aware opportunity evidence."""

    data = candidate_to_dict(candidate)
    symbol = str(data.get("symbol") or data.get("ticker") or "unknown").upper()
    threshold = (
        scanner_min_opportunity_score()
        if min_opportunity_score is None
        else max(0.0, min(1.0, float(min_opportunity_score)))
    )
    require_profile = (
        scanner_opportunity_profile_required()
        if profile_required is None
        else bool(profile_required)
    )
    require_spread = (
        scanner_opportunity_live_spread_required()
        if live_spread_required is None
        else bool(live_spread_required)
    )
    profile = scanner_candidate_opportunity_profile(candidate)

    if not profile:
        if require_profile:
            return _review_result(
                symbol=symbol,
                reason_code="SCANNER_OPPORTUNITY_PROFILE_MISSING",
                reason=(
                    "Scanner candidate has no scanner-opportunity-profile.v1; "
                    "automated entry is blocked while the profile is required."
                ),
                profile=None,
                min_score=threshold,
                profile_required=require_profile,
                live_spread_required=require_spread,
            )
        return {
            "symbol": symbol,
            "decision": "PASS",
            "allowed": True,
            "reason_code": "SCANNER_OPPORTUNITY_PROFILE_OPTIONAL_MISSING",
            "reason": (
                "Scanner opportunity profile is not present and the cross-repo "
                "rollout requirement is not enabled yet."
            ),
            "policy_version": SCANNER_OPPORTUNITY_POLICY_VERSION,
            "required_schema": SCANNER_OPPORTUNITY_PROFILE_SCHEMA,
            "schema_version": None,
            "profile_required": False,
            "live_spread_required": require_spread,
            "status": None,
            "opportunity_score": None,
            "min_opportunity_score": threshold,
            "preferred_strategy_hint": None,
            "execution_context": {},
            "profile_reasons": [],
            "compatibility_bypass": True,
        }

    schema = str(profile.get("schema_version") or "").strip()
    if schema != SCANNER_OPPORTUNITY_PROFILE_SCHEMA:
        return _review_result(
            symbol=symbol,
            reason_code="SCANNER_OPPORTUNITY_SCHEMA_UNSUPPORTED",
            reason=(
                "Scanner opportunity profile schema is unsupported; expected "
                f"{SCANNER_OPPORTUNITY_PROFILE_SCHEMA}."
            ),
            profile=profile,
            min_score=threshold,
            profile_required=require_profile,
            live_spread_required=require_spread,
        )

    if profile.get("is_binding") is not False or profile.get(
        "manager_decision_required"
    ) is not True:
        return _review_result(
            symbol=symbol,
            reason_code="SCANNER_OPPORTUNITY_AUTHORITY_INVALID",
            reason=(
                "Scanner opportunity evidence must remain non-binding and require "
                "a Manager decision."
            ),
            profile=profile,
            min_score=threshold,
            profile_required=require_profile,
            live_spread_required=require_spread,
        )

    status = str(profile.get("status") or "").strip().lower()
    if status not in _ALLOWED_STATUSES:
        return _review_result(
            symbol=symbol,
            reason_code="SCANNER_OPPORTUNITY_STATUS_INVALID",
            reason="Scanner opportunity status is missing or invalid.",
            profile=profile,
            min_score=threshold,
            profile_required=require_profile,
            live_spread_required=require_spread,
        )

    score = _finite_number(profile.get("opportunity_score"))
    if score is None or not 0.0 <= score <= 1.0:
        return _review_result(
            symbol=symbol,
            reason_code="SCANNER_OPPORTUNITY_SCORE_INVALID",
            reason="Scanner opportunity score is missing, non-finite, or out of range.",
            profile=profile,
            min_score=threshold,
            profile_required=require_profile,
            live_spread_required=require_spread,
        )

    hint = str(profile.get("preferred_strategy_hint") or "").strip().lower()
    if hint and hint not in _ALLOWED_STRATEGY_HINTS:
        return _review_result(
            symbol=symbol,
            reason_code="SCANNER_OPPORTUNITY_STRATEGY_HINT_INVALID",
            reason="Scanner opportunity strategy hint is outside the controlled vocabulary.",
            profile=profile,
            min_score=threshold,
            profile_required=require_profile,
            live_spread_required=require_spread,
        )

    context = _to_dict(profile.get("execution_context"))
    current_price = _finite_number(context.get("current_price"))
    dollar_volume = _finite_number(context.get("estimated_dollar_volume"))
    if current_price is None or current_price <= 0 or dollar_volume is None or dollar_volume <= 0:
        return _review_result(
            symbol=symbol,
            reason_code="SCANNER_OPPORTUNITY_EXECUTION_CONTEXT_INCOMPLETE",
            reason="Scanner opportunity profile lacks positive price or dollar-volume evidence.",
            profile=profile,
            min_score=threshold,
            profile_required=require_profile,
            live_spread_required=require_spread,
        )

    spread_bps = _finite_number(context.get("spread_bps"))
    if require_spread and (spread_bps is None or spread_bps < 0):
        return _review_result(
            symbol=symbol,
            reason_code="SCANNER_OPPORTUNITY_LIVE_SPREAD_MISSING",
            reason="Live spread evidence is required before automated entry.",
            profile=profile,
            min_score=threshold,
            profile_required=require_profile,
            live_spread_required=require_spread,
        )

    if status == "avoid":
        return _review_result(
            symbol=symbol,
            reason_code="SCANNER_OPPORTUNITY_AVOID",
            reason="Scanner opportunity evidence recommends avoiding a new entry.",
            profile=profile,
            min_score=threshold,
            profile_required=require_profile,
            live_spread_required=require_spread,
        )
    if status == "review":
        return _review_result(
            symbol=symbol,
            reason_code="SCANNER_OPPORTUNITY_REVIEW",
            reason="Scanner opportunity evidence requires review before a new entry.",
            profile=profile,
            min_score=threshold,
            profile_required=require_profile,
            live_spread_required=require_spread,
        )
    if score < threshold:
        return _review_result(
            symbol=symbol,
            reason_code="SCANNER_OPPORTUNITY_SCORE_BELOW_THRESHOLD",
            reason=(
                f"Scanner opportunity score {score:.4f} is below the Manager "
                f"minimum {threshold:.4f}."
            ),
            profile=profile,
            min_score=threshold,
            profile_required=require_profile,
            live_spread_required=require_spread,
        )

    return {
        "symbol": symbol,
        "decision": "PASS",
        "allowed": True,
        "reason_code": "SCANNER_OPPORTUNITY_ACCEPTED",
        "reason": "Scanner opportunity evidence satisfies the Manager gate.",
        "policy_version": SCANNER_OPPORTUNITY_POLICY_VERSION,
        "required_schema": SCANNER_OPPORTUNITY_PROFILE_SCHEMA,
        "schema_version": schema,
        "profile_required": require_profile,
        "live_spread_required": require_spread,
        "status": status,
        "opportunity_score": score,
        "min_opportunity_score": threshold,
        "preferred_strategy_hint": hint or None,
        "strategy_affinity": _to_dict(profile.get("strategy_affinity")),
        "execution_context": context,
        "profile_reasons": list(profile.get("reasons") or []),
        "compatibility_bypass": False,
    }


def partition_scanner_candidates_by_opportunity(
    candidates: Iterable[Any],
    *,
    min_opportunity_score: Optional[float] = None,
    profile_required: Optional[bool] = None,
    live_spread_required: Optional[bool] = None,
) -> Tuple[List[Any], List[Dict[str, Any]], Dict[str, Any]]:
    passed: List[Any] = []
    review: List[Dict[str, Any]] = []
    evaluations: List[Dict[str, Any]] = []

    for candidate in candidates or []:
        evaluation = evaluate_scanner_candidate_opportunity(
            candidate,
            min_opportunity_score=min_opportunity_score,
            profile_required=profile_required,
            live_spread_required=live_spread_required,
        )
        evaluations.append(evaluation)
        if evaluation["allowed"]:
            passed.append(candidate)
        else:
            review.append(evaluation)

    threshold = (
        scanner_min_opportunity_score()
        if min_opportunity_score is None
        else max(0.0, min(1.0, float(min_opportunity_score)))
    )
    required = (
        scanner_opportunity_profile_required()
        if profile_required is None
        else bool(profile_required)
    )
    require_spread = (
        scanner_opportunity_live_spread_required()
        if live_spread_required is None
        else bool(live_spread_required)
    )
    compatibility_bypass_count = sum(
        1 for row in evaluations if row.get("compatibility_bypass") is True
    )
    summary = {
        "policy_version": SCANNER_OPPORTUNITY_POLICY_VERSION,
        "required_schema": SCANNER_OPPORTUNITY_PROFILE_SCHEMA,
        "profile_required": required,
        "live_spread_required": require_spread,
        "min_opportunity_score": threshold,
        "original_count": len(evaluations),
        "passed_count": len(passed),
        "review_count": len(review),
        "compatibility_bypass_count": compatibility_bypass_count,
        "decision": "REVIEW" if review and not passed else "PARTIAL" if review else "PASS",
        "review_reason_codes": sorted({row["reason_code"] for row in review}),
        "evaluations": evaluations,
    }
    return passed, review, summary

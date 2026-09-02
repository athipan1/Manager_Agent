from __future__ import annotations

from typing import Any, Mapping

STRATEGY_AWARE_SIZING_POLICY_VERSION = "manager-strategy-aware-sizing.v1"


def _mapping(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return dict(value) if isinstance(value, Mapping) else {}


def _float_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def opportunity_profile_from_candidate(candidate: Any) -> dict[str, Any]:
    """Extract Scanner opportunity evidence from a Manager candidate contract."""

    payload = _mapping(candidate)
    metadata = _mapping(payload.get("metadata"))
    bundle = _mapping(metadata.get("data_bundle"))
    if not bundle:
        bundle = _mapping(_mapping(metadata.get("details")).get("data_bundle"))
    return _mapping(bundle.get("opportunity_profile"))


def strategy_aware_size_multiplier(opportunity_profile: Any) -> float:
    """Return the conservative production size cap for Scanner strategy-aware entries.

    Generic qualification preserves the existing size. Strategy-aware qualification
    converts marginal generic opportunity evidence into smaller exposure rather than
    weakening any hard quote, spread, Backtest, Risk, or Execution gate. Malformed or
    unsafe strategy-aware evidence fails closed with a zero size multiplier.
    """

    profile = _mapping(opportunity_profile)
    if str(profile.get("status") or "").strip().lower() != "qualified":
        return 1.0

    qualification = _mapping(profile.get("qualification_policy"))
    if str(qualification.get("mode") or "").strip().lower() != "strategy_aware":
        return 1.0
    if qualification.get("hard_execution_safe") is not True:
        return 0.0
    if qualification.get("hard_execution_thresholds_relaxed") is True:
        return 0.0

    generic_score = _float_value(
        qualification.get("generic_score"),
        _float_value(profile.get("opportunity_score"), 0.0),
    )
    if generic_score < 0.60:
        return 0.25
    if generic_score < 0.70:
        return 0.50
    return 1.0


def strategy_aware_size_multiplier_from_candidate(candidate: Any) -> float:
    return strategy_aware_size_multiplier(opportunity_profile_from_candidate(candidate))

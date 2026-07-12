from __future__ import annotations

import os
from typing import Any, Dict, List


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


def _float_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return min(1.0, max(0.0, value))


def _int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def evaluate_curator_required_mode_readiness(
    summary: Dict[str, Any] | None,
) -> Dict[str, Any]:
    """Evaluate whether required mode is eligible for operator approval.

    This function is advisory only. It never mutates environment variables and
    never enables Curator required mode automatically.
    """
    data = summary if isinstance(summary, dict) else {}
    observation_target = _int_env("CURATOR_REQUIRED_MODE_MIN_OBSERVATIONS", 50)
    minimum_availability = _float_env(
        "CURATOR_REQUIRED_MODE_MIN_AVAILABILITY",
        0.99,
    )
    minimum_contract_valid_rate = _float_env(
        "CURATOR_REQUIRED_MODE_MIN_CONTRACT_VALID_RATE",
        1.0,
    )
    minimum_would_pass = _int_env("CURATOR_REQUIRED_MODE_MIN_WOULD_PASS", 1)

    observations = _int(data.get("ensemble_observations") or data.get("observations"))
    availability_rate = _float(data.get("availability_rate"))
    contract_valid_rate = _float(data.get("contract_valid_rate"))
    unsafe_contract_count = _int(data.get("unsafe_contract_count"))
    would_pass = _int(data.get("would_pass_required_gate"))
    source = str(data.get("readiness_source") or "current_run")

    blockers: List[str] = []
    if source != "database_cumulative":
        blockers.append("cumulative_readiness_unavailable")
    if observations < observation_target:
        blockers.append("observations_below_target")
    if availability_rate is None or availability_rate < minimum_availability:
        blockers.append("availability_below_threshold")
    if (
        contract_valid_rate is None
        or contract_valid_rate < minimum_contract_valid_rate
    ):
        blockers.append("contract_valid_rate_below_threshold")
    if unsafe_contract_count > 0:
        blockers.append("unsafe_contracts_detected")
    if would_pass < minimum_would_pass:
        blockers.append("no_candidates_would_pass_required_gate")

    eligible = not blockers
    status = "eligible_for_operator_approval" if eligible else "not_ready"
    return {
        "status": status,
        "eligible": eligible,
        "operator_approval_required": True,
        "automatic_activation_allowed": False,
        "recommended_action": (
            "review_and_manually_enable_required_mode"
            if eligible
            else "continue_advisory_observation"
        ),
        "readiness_source": source,
        "observations": observations,
        "thresholds": {
            "minimum_observations": observation_target,
            "minimum_availability_rate": minimum_availability,
            "minimum_contract_valid_rate": minimum_contract_valid_rate,
            "maximum_unsafe_contracts": 0,
            "minimum_would_pass_required_gate": minimum_would_pass,
        },
        "metrics": {
            "availability_rate": availability_rate,
            "contract_valid_rate": contract_valid_rate,
            "unsafe_contract_count": unsafe_contract_count,
            "would_pass_required_gate": would_pass,
        },
        "blockers": blockers,
        "alert": {
            "severity": "action_required" if eligible else "info",
            "code": (
                "curator_required_mode_operator_approval_ready"
                if eligible
                else "curator_required_mode_not_ready"
            ),
            "message": (
                "Curator required mode meets readiness thresholds and is ready "
                "for explicit operator review. It has not been enabled automatically."
                if eligible
                else "Curator remains in advisory mode until all readiness "
                "thresholds are satisfied."
            ),
        },
    }

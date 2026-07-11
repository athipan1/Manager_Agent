from __future__ import annotations

import os
from typing import Any, Dict

from .curator_client import CURATOR_AGENT_URL, json_safe_value
from .resilient_client import ResilientAgentClient


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


CURATOR_SHADOW_ENSEMBLE_TIMEOUT = _env_float(
    "CURATOR_SHADOW_ENSEMBLE_TIMEOUT",
    8.0,
)
CURATOR_SHADOW_ENSEMBLE_MAX_RETRIES = _env_int(
    "CURATOR_SHADOW_ENSEMBLE_MAX_RETRIES",
    1,
)
CURATOR_SHADOW_ENSEMBLE_FAILURE_THRESHOLD = _env_int(
    "CURATOR_SHADOW_ENSEMBLE_FAILURE_THRESHOLD",
    2,
)
CURATOR_SHADOW_ENSEMBLE_COOLDOWN_SECONDS = _env_int(
    "CURATOR_SHADOW_ENSEMBLE_COOLDOWN_SECONDS",
    30,
)


class CuratorShadowEnsembleClient(ResilientAgentClient):
    """Client for Curator's advisory-only shadow ensemble endpoint."""

    def __init__(self) -> None:
        super().__init__(
            base_url=CURATOR_AGENT_URL,
            timeout=CURATOR_SHADOW_ENSEMBLE_TIMEOUT,
            max_retries=CURATOR_SHADOW_ENSEMBLE_MAX_RETRIES,
            failure_threshold=CURATOR_SHADOW_ENSEMBLE_FAILURE_THRESHOLD,
            cooldown_period=CURATOR_SHADOW_ENSEMBLE_COOLDOWN_SECONDS,
        )

    async def execute_shadow_ensemble(
        self,
        *,
        inputs: Dict[str, Any],
        correlation_id: str,
        minimum_agreement: float = 0.60,
        max_skills: int = 8,
    ) -> Dict[str, Any]:
        payload = {
            "inputs": json_safe_value(inputs),
            "minimum_agreement": minimum_agreement,
            "max_skills": max_skills,
        }
        response = await self._post(
            "/skills/shadow-ensemble",
            correlation_id,
            json_data=payload,
        )
        if response.get("status") != "success":
            raise ValueError(
                response.get("error")
                or response.get("detail")
                or "Curator shadow ensemble failed"
            )
        data = response.get("data")
        if not isinstance(data, dict):
            raise ValueError("Curator shadow ensemble data must be an object")
        return data


def validate_shadow_ensemble_contract(
    data: Dict[str, Any],
    *,
    minimum_agreement: float,
) -> Dict[str, Any]:
    """Validate Curator's safety contract and derive a fail-closed gate decision."""
    reasons: list[str] = []
    consensus = data.get("consensus") if isinstance(data.get("consensus"), dict) else {}
    manager_contract = (
        data.get("manager_contract")
        if isinstance(data.get("manager_contract"), dict)
        else {}
    )

    trusted_signal = str(manager_contract.get("trusted_signal") or "").lower()
    consensus_signal = str(consensus.get("signal") or "").lower()
    consensus_state = str(consensus.get("state") or "").lower()

    try:
        agreement = float(consensus.get("agreement"))
    except (TypeError, ValueError):
        agreement = -1.0
        reasons.append("agreement_not_numeric")

    if data.get("advisory_only") is not True:
        reasons.append("advisory_only_must_be_true")
    if data.get("broker_access") is not False:
        reasons.append("broker_access_must_be_false")
    if data.get("order_placement") is not False:
        reasons.append("order_placement_must_be_false")
    if manager_contract.get("requires_risk_gate") is not True:
        reasons.append("requires_risk_gate_must_be_true")
    if manager_contract.get("direct_execution_allowed") is not False:
        reasons.append("direct_execution_allowed_must_be_false")
    if trusted_signal not in {"buy", "hold", "sell"}:
        reasons.append("trusted_signal_invalid")
    if consensus_signal not in {"buy", "hold", "sell"}:
        reasons.append("consensus_signal_invalid")
    if trusted_signal and consensus_signal and trusted_signal != consensus_signal:
        reasons.append("trusted_signal_consensus_mismatch")
    if not 0.0 <= agreement <= 1.0:
        reasons.append("agreement_out_of_range")

    contract_valid = not reasons
    allowed = (
        contract_valid
        and trusted_signal == "buy"
        and consensus_signal == "buy"
        and consensus_state == "consensus"
        and agreement >= minimum_agreement
    )
    if contract_valid and not allowed:
        if trusted_signal != "buy":
            reasons.append("trusted_signal_not_buy")
        if consensus_state != "consensus":
            reasons.append("consensus_state_not_consensus")
        if agreement < minimum_agreement:
            reasons.append("agreement_below_threshold")

    return {
        "allowed": allowed,
        "contract_valid": contract_valid,
        "trusted_signal": trusted_signal or "hold",
        "consensus_signal": consensus_signal or "hold",
        "consensus_state": consensus_state or "unknown",
        "agreement": agreement if agreement >= 0 else None,
        "minimum_agreement": minimum_agreement,
        "rejection_codes": reasons,
        "requires_risk_gate": manager_contract.get("requires_risk_gate") is True,
        "direct_execution_allowed": manager_contract.get("direct_execution_allowed"),
    }

from __future__ import annotations

from typing import Any, Dict, Iterable, List

from app.database_client import DatabaseAgentClient
from app.logger import report_logger


CURATOR_OBSERVATION_BATCH_ENDPOINT = "/curator/observations/batch"


def _count_from(value: Any) -> int:
    if isinstance(value, list):
        return len(value)
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def build_curator_observations(
    curator_signals: Iterable[Dict[str, Any]],
    *,
    correlation_id: str,
) -> List[Dict[str, Any]]:
    observations: List[Dict[str, Any]] = []
    for signal in curator_signals or []:
        symbol = str(signal.get("symbol") or "").upper()
        account_id = signal.get("account_id")
        if not symbol or account_id is None:
            continue

        gate = signal.get("gate") if isinstance(signal.get("gate"), dict) else {}
        ensemble = (
            signal.get("ensemble")
            if isinstance(signal.get("ensemble"), dict)
            else {}
        )
        consensus = (
            ensemble.get("consensus")
            if isinstance(ensemble.get("consensus"), dict)
            else {}
        )
        executions = ensemble.get("executions") or ensemble.get("results") or []
        selected_skills = ensemble.get("selected_skills") or ensemble.get("skills") or []
        rejection_codes = gate.get("rejection_codes") or []
        if not isinstance(rejection_codes, list):
            rejection_codes = [str(rejection_codes)]

        status = str(signal.get("status") or "unknown")
        available = status not in {"unavailable", "error", "failed"}
        signal_value = str(
            gate.get("trusted_signal")
            or gate.get("consensus_signal")
            or consensus.get("signal")
            or "unknown"
        ).lower()
        if signal_value not in {"buy", "hold", "sell", "unknown"}:
            signal_value = "unknown"

        observations.append(
            {
                "account_id": account_id,
                "correlation_id": correlation_id,
                "symbol": symbol,
                "mode": str(signal.get("mode") or "single_skill"),
                "status": status,
                "available": available,
                "signal": signal_value,
                "agreement": gate.get("agreement", consensus.get("agreement")),
                "contract_valid": gate.get("contract_valid"),
                "would_pass_required_gate": gate.get("allowed"),
                "selected_skill_count": _count_from(selected_skills),
                "execution_count": _count_from(executions),
                "minimum_agreement": gate.get("minimum_agreement"),
                "rejection_codes": [str(code) for code in rejection_codes],
                "metadata": {
                    "source": "manager-agent",
                    "consensus_state": gate.get("consensus_state")
                    or consensus.get("state"),
                    "requires_risk_gate": gate.get("requires_risk_gate"),
                    "direct_execution_allowed": gate.get(
                        "direct_execution_allowed"
                    ),
                    "reason": signal.get("reason"),
                },
            }
        )
    return observations


async def persist_curator_observations_best_effort(
    curator_signals: Iterable[Dict[str, Any]],
    *,
    correlation_id: str,
) -> Dict[str, Any]:
    observations = build_curator_observations(
        curator_signals,
        correlation_id=correlation_id,
    )
    if not observations:
        return {"status": "skipped", "created_count": 0}

    try:
        async with DatabaseAgentClient() as client:
            response_data = await client._post(
                CURATOR_OBSERVATION_BATCH_ENDPOINT,
                correlation_id,
                json_data={"observations": observations},
            )
            response = client.validate_standard_response(response_data)
        data = response.data if isinstance(response.data, dict) else {}
        return {
            "status": "success",
            "created_count": int(data.get("created_count") or len(observations)),
        }
    except Exception as exc:
        report_logger.warning(
            "Failed to persist Curator observations: %s, correlation_id=%s",
            exc,
            correlation_id,
        )
        return {
            "status": "unavailable",
            "created_count": 0,
            "reason": str(exc),
        }

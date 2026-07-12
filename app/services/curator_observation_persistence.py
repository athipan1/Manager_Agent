from __future__ import annotations

from typing import Any, Dict, Iterable, List, Union

from ..contracts import DatabaseEndpoints
from ..database_client import DatabaseAgentClient
from ..logger import report_logger
from .curator_observability import normalize_curator_observation

_ALLOWED_SIGNALS = {"buy", "hold", "sell", "unknown"}
_ALLOWED_MODES = {"shadow_ensemble", "single_skill"}


def build_curator_observation_payloads(
    *,
    account_id: Union[int, str],
    correlation_id: str,
    curator_signals: Iterable[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build the normalized Database_Agent batch contract.

    The Database Agent derives deterministic observation IDs from account,
    correlation ID, symbol, and mode, so replaying the same Manager run remains
    idempotent while separate hourly runs continue to accumulate observations.
    """
    payloads: List[Dict[str, Any]] = []
    for raw_signal in curator_signals or []:
        if not isinstance(raw_signal, dict):
            continue
        normalized = normalize_curator_observation(raw_signal)
        symbol = str(normalized.get("symbol") or "").strip().upper()
        if not symbol or symbol == "-":
            continue

        mode = str(normalized.get("mode") or "single_skill")
        if mode not in _ALLOWED_MODES:
            mode = "single_skill"
        signal = str(normalized.get("signal") or "unknown").lower()
        if signal not in _ALLOWED_SIGNALS:
            signal = "unknown"

        payloads.append(
            {
                "account_id": account_id,
                "correlation_id": correlation_id,
                "symbol": symbol,
                "mode": mode,
                "status": str(normalized.get("status") or "unknown")[:80],
                "available": bool(normalized.get("available", False)),
                "signal": signal,
                "agreement": normalized.get("agreement"),
                "contract_valid": normalized.get("contract_valid"),
                "would_pass_required_gate": normalized.get(
                    "would_pass_required_gate"
                ),
                "selected_skill_count": int(
                    normalized.get("selected_skill_count") or 0
                ),
                "execution_count": int(normalized.get("execution_count") or 0),
                "minimum_agreement": normalized.get("minimum_agreement"),
                "rejection_codes": list(
                    normalized.get("rejection_codes") or []
                ),
                "metadata": {
                    "schema": "curator_observation.v1",
                    "source_agent": "manager-agent",
                    "deployment_mode": (
                        "advisory"
                        if mode == "shadow_ensemble"
                        else "legacy_single_skill"
                    ),
                },
            }
        )
    return payloads


async def persist_curator_observations(
    *,
    db_client: DatabaseAgentClient,
    account_id: Union[int, str],
    correlation_id: str,
    curator_signals: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """Persist one Manager run and return cumulative readiness, fail-soft.

    Telemetry persistence must never interrupt risk evaluation or execution.
    Errors are attached to the Manager response and logged for operators.
    """
    observations = build_curator_observation_payloads(
        account_id=account_id,
        correlation_id=correlation_id,
        curator_signals=curator_signals,
    )
    if not observations:
        return {
            "status": "skipped",
            "reason": "no_curator_observations",
            "attempted_count": 0,
            "persisted_count": 0,
            "readiness": None,
        }

    try:
        response_data = await db_client._post(
            DatabaseEndpoints.CURATOR_OBSERVATIONS_BATCH,
            correlation_id,
            json_data={"observations": observations},
        )
        response = db_client.validate_standard_response(response_data)
        batch_data = response.data if isinstance(response.data, dict) else {}
        persisted_count = int(
            batch_data.get("created_count")
            or len(batch_data.get("observations") or [])
            or 0
        )
    except Exception as exc:
        report_logger.warning(
            "Failed to persist Curator observations: "
            f"{exc}, correlation_id={correlation_id}"
        )
        return {
            "status": "failed",
            "reason": "database_persistence_failed",
            "error": str(exc),
            "attempted_count": len(observations),
            "persisted_count": 0,
            "readiness": None,
        }

    readiness = None
    readiness_error = None
    try:
        readiness_response_data = await db_client._get(
            DatabaseEndpoints.CURATOR_OBSERVATION_READINESS,
            correlation_id,
            params={
                "account_id": account_id,
                "mode": "shadow_ensemble",
                "observation_target": 50,
            },
        )
        readiness_response = db_client.validate_standard_response(
            readiness_response_data
        )
        if isinstance(readiness_response.data, dict):
            readiness = readiness_response.data
    except Exception as exc:
        readiness_error = str(exc)
        report_logger.warning(
            "Curator observations were persisted but cumulative readiness "
            f"could not be loaded: {exc}, correlation_id={correlation_id}"
        )

    result = {
        "status": "persisted",
        "attempted_count": len(observations),
        "persisted_count": persisted_count,
        "readiness": readiness,
    }
    if readiness_error:
        result["readiness_error"] = readiness_error
    return result

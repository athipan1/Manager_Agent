from __future__ import annotations

from typing import Any, Dict, Iterable, List


OBSERVATION_TARGET = 50


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _agreement(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if 0.0 <= result <= 1.0 else None


def _integer(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def normalize_curator_observation(signal: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize legacy and shadow-ensemble Curator results for telemetry/reporting."""
    row = _dict(signal)
    gate = _dict(row.get("gate"))
    ensemble = _dict(row.get("ensemble"))
    consensus = _dict(ensemble.get("consensus"))
    manager_contract = _dict(ensemble.get("manager_contract"))
    execution = _dict(row.get("execution"))
    output = _dict(execution.get("output"))

    mode = str(row.get("mode") or "single_skill")
    is_ensemble = mode == "shadow_ensemble"
    signal_value = str(
        gate.get("trusted_signal")
        or manager_contract.get("trusted_signal")
        or consensus.get("signal")
        or output.get("signal")
        or "unknown"
    ).lower()
    agreement = _agreement(gate.get("agreement"))
    if agreement is None:
        agreement = _agreement(consensus.get("agreement"))

    available = str(row.get("status") or "").lower() not in {
        "unavailable",
        "failed",
        "error",
    }
    contract_valid = gate.get("contract_valid") if is_ensemble else None
    would_pass = gate.get("allowed") if is_ensemble else None
    rejection_codes = [
        str(item)
        for item in _list(gate.get("rejection_codes"))
        if item not in (None, "")
    ]

    return {
        "symbol": str(row.get("symbol") or "-").upper(),
        "mode": mode,
        "available": available,
        "status": row.get("status") or "unknown",
        "signal": signal_value,
        "agreement": agreement,
        "contract_valid": contract_valid,
        "would_pass_required_gate": would_pass,
        "rejection_codes": rejection_codes,
        "selected_skill_count": _integer(ensemble.get("selected_skill_count")),
        "execution_count": len(_list(ensemble.get("executions"))),
        "minimum_agreement": gate.get("minimum_agreement"),
    }


def summarize_curator_signals(signals: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    observations = [normalize_curator_observation(row) for row in signals or []]
    ensemble_rows = [row for row in observations if row["mode"] == "shadow_ensemble"]
    active_rows = ensemble_rows or observations
    available_rows = [row for row in active_rows if row["available"]]
    agreements = [row["agreement"] for row in active_rows if row["agreement"] is not None]
    signal_counts = {
        signal: sum(1 for row in active_rows if row["signal"] == signal)
        for signal in ("buy", "hold", "sell", "unknown")
    }
    contract_valid_count = sum(
        1 for row in ensemble_rows if row["contract_valid"] is True
    )
    contract_invalid_count = sum(
        1 for row in ensemble_rows if row["contract_valid"] is False
    )
    would_pass = sum(
        1 for row in ensemble_rows if row["would_pass_required_gate"] is True
    )
    would_block = sum(
        1 for row in ensemble_rows if row["would_pass_required_gate"] is not True
    )
    unsafe_contract_count = sum(
        1
        for row in ensemble_rows
        if any(
            code in {
                "advisory_only_must_be_true",
                "broker_access_must_be_false",
                "order_placement_must_be_false",
                "requires_risk_gate_must_be_true",
                "direct_execution_allowed_must_be_false",
            }
            for code in row["rejection_codes"]
        )
    )
    availability_rate = (
        len(available_rows) / len(active_rows) if active_rows else None
    )
    contract_valid_rate = (
        contract_valid_count / len(ensemble_rows) if ensemble_rows else None
    )
    average_agreement = (
        sum(agreements) / len(agreements) if agreements else None
    )
    readiness_eligible = bool(
        len(ensemble_rows) >= OBSERVATION_TARGET
        and availability_rate is not None
        and availability_rate >= 0.99
        and contract_valid_rate == 1.0
        and unsafe_contract_count == 0
    )

    return {
        "mode": "shadow_ensemble" if ensemble_rows else "single_skill",
        "observations": len(active_rows),
        "ensemble_observations": len(ensemble_rows),
        "available": len(available_rows),
        "unavailable": len(active_rows) - len(available_rows),
        "availability_rate": availability_rate,
        "contract_valid": contract_valid_count,
        "contract_invalid": contract_invalid_count,
        "contract_valid_rate": contract_valid_rate,
        "unsafe_contract_count": unsafe_contract_count,
        "signal_counts": signal_counts,
        "average_agreement": average_agreement,
        "would_pass_required_gate": would_pass,
        "would_be_blocked": would_block,
        "observation_target": OBSERVATION_TARGET,
        "required_mode_eligible": readiness_eligible,
        "rows": observations,
    }

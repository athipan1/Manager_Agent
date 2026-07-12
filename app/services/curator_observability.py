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


def _cumulative_readiness(
    signals: List[Dict[str, Any]],
    readiness: Dict[str, Any] | None,
) -> Dict[str, Any]:
    direct = _dict(readiness)
    if direct:
        return direct
    for signal in signals:
        nested = _dict(_dict(signal).get("cumulative_readiness"))
        if nested:
            return nested
    return {}


def summarize_curator_signals(
    signals: Iterable[Dict[str, Any]],
    *,
    cumulative_readiness: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    raw_signals = list(signals or [])
    observations = [normalize_curator_observation(row) for row in raw_signals]
    ensemble_rows = [row for row in observations if row["mode"] == "shadow_ensemble"]
    active_rows = ensemble_rows or observations
    available_rows = [row for row in active_rows if row["available"]]
    agreements = [
        row["agreement"] for row in active_rows if row["agreement"] is not None
    ]
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

    cumulative = _cumulative_readiness(raw_signals, cumulative_readiness)
    use_cumulative = bool(cumulative)
    cumulative_counts = {
        "buy": _integer(cumulative.get("buy_count")),
        "hold": _integer(cumulative.get("hold_count")),
        "sell": _integer(cumulative.get("sell_count")),
        "unknown": _integer(cumulative.get("unknown_count")),
    }

    return {
        "mode": "shadow_ensemble" if ensemble_rows else "single_skill",
        "readiness_source": (
            "database_cumulative" if use_cumulative else "current_run"
        ),
        "observations": (
            _integer(cumulative.get("observations"), len(active_rows))
            if use_cumulative
            else len(active_rows)
        ),
        "ensemble_observations": (
            _integer(cumulative.get("observations"), len(ensemble_rows))
            if use_cumulative
            else len(ensemble_rows)
        ),
        "available": (
            _integer(cumulative.get("available"), len(available_rows))
            if use_cumulative
            else len(available_rows)
        ),
        "unavailable": (
            _integer(
                cumulative.get("unavailable"),
                len(active_rows) - len(available_rows),
            )
            if use_cumulative
            else len(active_rows) - len(available_rows)
        ),
        "availability_rate": (
            cumulative.get("availability_rate")
            if use_cumulative
            else availability_rate
        ),
        "contract_valid": (
            _integer(cumulative.get("contract_valid"), contract_valid_count)
            if use_cumulative
            else contract_valid_count
        ),
        "contract_invalid": (
            _integer(cumulative.get("contract_invalid"), contract_invalid_count)
            if use_cumulative
            else contract_invalid_count
        ),
        "contract_valid_rate": (
            cumulative.get("contract_valid_rate")
            if use_cumulative
            else contract_valid_rate
        ),
        "unsafe_contract_count": (
            _integer(
                cumulative.get("unsafe_contract_count"),
                unsafe_contract_count,
            )
            if use_cumulative
            else unsafe_contract_count
        ),
        "signal_counts": cumulative_counts if use_cumulative else signal_counts,
        "average_agreement": (
            cumulative.get("average_agreement")
            if use_cumulative
            else average_agreement
        ),
        "would_pass_required_gate": (
            _integer(cumulative.get("would_pass_required_gate"), would_pass)
            if use_cumulative
            else would_pass
        ),
        "would_be_blocked": (
            _integer(cumulative.get("would_be_blocked"), would_block)
            if use_cumulative
            else would_block
        ),
        "observation_target": _integer(
            cumulative.get("observation_target"),
            OBSERVATION_TARGET,
        ),
        "required_mode_eligible": (
            bool(cumulative.get("required_mode_eligible"))
            if use_cumulative
            else readiness_eligible
        ),
        "readiness_blockers": (
            _list(cumulative.get("blockers")) if use_cumulative else []
        ),
        "current_run": {
            "observations": len(active_rows),
            "available": len(available_rows),
            "unavailable": len(active_rows) - len(available_rows),
            "signal_counts": signal_counts,
            "would_pass_required_gate": would_pass,
            "would_be_blocked": would_block,
        },
        "rows": observations,
    }

from __future__ import annotations

import math
from collections import Counter
from typing import Any, Dict, Iterable, Mapping, Optional


LIQUIDITY_COVERAGE_VERSION = "hourly-liquidity-coverage-v1"


def _dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _finite_number(value: Any, *, minimum: float = 0.0) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number) or number < minimum:
        return None
    return number


def _coverage(available: int, total: int) -> tuple[float, float]:
    if total <= 0:
        return 0.0, 0.0
    ratio = round(available / total, 4)
    return ratio, round(ratio * 100.0, 1)


def _technical_evidence(row: Mapping[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any]]:
    evidence_summary = _dict(row.get("evidence_summary"))
    technical = _dict(evidence_summary.get("technical"))
    metrics = _dict(technical.get("metrics"))
    provenance = _dict(technical.get("provenance"))

    if not metrics:
        metrics = _dict(_dict(evidence_summary.get("metrics")).get("technical"))
    if not provenance:
        provenance = _dict(
            _dict(evidence_summary.get("provenance")).get("technical")
        )
    return metrics, provenance


def summarize_liquidity_coverage(
    ranked_candidates: Iterable[Mapping[str, Any]] | None,
) -> Dict[str, Any]:
    """Summarize observable liquidity fields across ranked candidates.

    Coverage is evidence availability, not a pass/fail investability decision.
    A field counts as available only when it is finite and within its valid
    numeric domain. Missing bid/ask spread remains explicit and is never
    inferred from historical bars.
    """

    rows = [row for row in (ranked_candidates or []) if isinstance(row, Mapping)]
    total = len(rows)
    average_daily_volume_count = 0
    average_dollar_volume_count = 0
    spread_count = 0
    version_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    quote_source_counts: Counter[str] = Counter()

    for row in rows:
        metrics, provenance = _technical_evidence(row)
        gate_metrics = _dict(_dict(row.get("investability_gate")).get("metrics"))

        average_daily_volume = _finite_number(
            metrics.get("average_daily_volume"),
            minimum=0.0,
        )
        average_dollar_volume = _finite_number(
            metrics.get("average_dollar_volume")
            if metrics.get("average_dollar_volume") is not None
            else gate_metrics.get("average_dollar_volume"),
            minimum=0.0,
        )
        spread_bps = _finite_number(
            metrics.get("spread_bps")
            if metrics.get("spread_bps") is not None
            else gate_metrics.get("spread_bps"),
            minimum=0.0,
        )

        if average_daily_volume is not None:
            average_daily_volume_count += 1
        if average_dollar_volume is not None:
            average_dollar_volume_count += 1
        if spread_bps is not None:
            spread_count += 1

        version = str(
            provenance.get("liquidity_evidence_version") or "unavailable"
        ).strip()
        status = str(
            provenance.get("liquidity_evidence_status") or "unavailable"
        ).strip()
        quote_source = str(
            provenance.get("liquidity_quote_source") or "unavailable"
        ).strip()
        version_counts[version or "unavailable"] += 1
        status_counts[status or "unavailable"] += 1
        quote_source_counts[quote_source or "unavailable"] += 1

    adv_ratio, adv_pct = _coverage(average_daily_volume_count, total)
    dollar_ratio, dollar_pct = _coverage(average_dollar_volume_count, total)
    spread_ratio, spread_pct = _coverage(spread_count, total)

    return {
        "summary_version": LIQUIDITY_COVERAGE_VERSION,
        "population": "ranked_candidates",
        "candidate_count": total,
        "average_daily_volume_available_count": average_daily_volume_count,
        "average_daily_volume_coverage": adv_ratio,
        "average_daily_volume_coverage_pct": adv_pct,
        "average_dollar_volume_available_count": average_dollar_volume_count,
        "average_dollar_volume_coverage": dollar_ratio,
        "average_dollar_volume_coverage_pct": dollar_pct,
        "spread_available_count": spread_count,
        "spread_coverage": spread_ratio,
        "spread_coverage_pct": spread_pct,
        "liquidity_evidence_version_counts": dict(sorted(version_counts.items())),
        "liquidity_evidence_status_counts": dict(sorted(status_counts.items())),
        "quote_source_counts": dict(sorted(quote_source_counts.items())),
        "average_dollar_volume_required_gate_ready": (
            total > 0 and average_dollar_volume_count == total
        ),
        "spread_required_gate_ready": total > 0 and spread_count == total,
        "safety_note": (
            "Coverage reports evidence availability only; Manager investability "
            "thresholds remain authoritative."
        ),
    }


def runtime_report_metadata(mode: Any, broker_mode: Any) -> Dict[str, Any]:
    """Return report mode metadata whose warning matches the actual run mode."""

    normalized_mode = str(mode or "").strip().upper()
    normalized_broker_mode = str(broker_mode or "").strip().upper()
    paper_enabled = (
        normalized_mode == "ALPACA_PAPER"
        and normalized_broker_mode == "ALPACA"
    )
    if paper_enabled:
        return {
            "mode": "ALPACA_PAPER",
            "broker_mode": "ALPACA",
            "warning": (
                "Alpaca Paper execution mode is active; eligible orders may be "
                "submitted only to the Alpaca Paper endpoint."
            ),
            "broker_order_submission_possible": True,
        }
    return {
        "mode": "SIMULATOR",
        "broker_mode": normalized_broker_mode or "SIMULATOR",
        "warning": (
            "Simulator safety mode is active; no broker orders will be submitted."
        ),
        "broker_order_submission_possible": False,
    }


def enrich_hourly_artifact(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize mode warning and inject liquidity coverage into artifact JSON."""

    result = dict(raw)
    runtime = runtime_report_metadata(
        result.get("mode"),
        result.get("broker_mode"),
    )
    result.update(runtime)

    response = _dict(result.get("response"))
    response_data = _dict(response.get("data"))
    if isinstance(response_data.get("data"), Mapping):
        response_data = _dict(response_data.get("data"))

    summary = summarize_liquidity_coverage(
        _list(response_data.get("ranked_candidates"))
    )
    result["liquidity_coverage_summary"] = summary
    if response:
        response["data"] = {
            **response_data,
            "liquidity_coverage_summary": summary,
        }
        result["response"] = response
    return result

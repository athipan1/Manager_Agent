#!/usr/bin/env python3
"""Publish bounded decision analytics and safety alerts from public decision history."""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "decision-analytics.v1"
HISTORY_SCHEMA_VERSION = "decision-history.v1"
OBSERVABILITY_SCHEMA_VERSION = "trading-observability.v1"
WINDOW_SIZES = (6, 12, 24)
MAX_TOP_REASONS = 8
MAX_ALERTS = 8
STAGE_ORDER = (
    "scanner",
    "backtest",
    "market_regime",
    "portfolio",
    "profit",
    "risk",
    "execution",
)
SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
SAFE_CODE_PATTERN = re.compile(r"[^a-zA-Z0-9_.:-]+")
SECRET_PATTERN = re.compile(
    r"(?i)(authorization|bearer\s+[a-z0-9._-]+|github[_-]?token|operator[_-]?token|"
    r"api[_-]?key|secret[_-]?key|password|database[_-]?(url|credentials?)|"
    r"client[_-]?order[_-]?id|ghp_[a-z0-9]+|github_pat_[a-z0-9_]+)"
)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return _dict(value)


def _safe_code(value: Any, *, limit: int = 96) -> str | None:
    if value in (None, ""):
        return None
    text = " ".join(str(value).split())[:limit]
    if SECRET_PATTERN.search(text):
        return "redacted"
    code = SAFE_CODE_PATTERN.sub("_", text.strip()).strip("_").lower()
    return code[:limit] or None


def _safe_text(value: Any, *, limit: int = 96) -> str | None:
    if value in (None, ""):
        return None
    text = " ".join(str(value).split())[:limit]
    return "redacted" if SECRET_PATTERN.search(text) else (text or None)


def _number(value: Any, minimum: float | None = None, maximum: float | None = None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(parsed):
        return None
    if minimum is not None and parsed < minimum:
        return None
    if maximum is not None and parsed > maximum:
        return None
    return parsed


def _integer(value: Any, minimum: int = 0) -> int:
    parsed = _number(value, minimum)
    return int(parsed) if parsed is not None else 0


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator, 6)


def _stage_map(cycle: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for raw in _list(cycle.get("stages")):
        row = _dict(raw)
        stage_id = _safe_code(row.get("id"))
        if stage_id in STAGE_ORDER:
            output[stage_id] = row
    return output


def _valid_cycle(cycle: Mapping[str, Any]) -> bool:
    row = _dict(cycle)
    if row.get("flowKind") != "decision_path":
        return False
    return [stage.get("id") for stage in _list(row.get("stages"))] == list(STAGE_ORDER)


def _meaningful_cycles(cycles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [cycle for cycle in cycles if cycle.get("source") == "hourly_artifact"]


def _candidate_stage_index(candidate: Mapping[str, Any]) -> int | None:
    stage = _safe_code(candidate.get("stageReached"))
    try:
        return STAGE_ORDER.index(stage) if stage else None
    except ValueError:
        return None


def _aggregate_window(cycles: list[dict[str, Any]], size: int) -> dict[str, Any]:
    selected = cycles[:size]
    candidates: list[dict[str, Any]] = []
    for cycle in selected:
        candidates.extend(_dict(item) for item in _list(cycle.get("candidates"))[:10])

    candidate_count = len(candidates)
    buy_count = sum(_safe_code(item.get("verdict")) == "buy" for item in candidates)
    blocked = [item for item in candidates if _safe_code(item.get("status")) == "blocked"]
    blocked_count = len(blocked)
    executed_count = sum(_safe_code(item.get("status")) == "executed" for item in candidates)
    risk_rejected_count = sum(
        _safe_code(item.get("stageReached")) == "risk"
        and (
            _safe_code(item.get("status")) == "blocked"
            or "risk_rejected" in {_safe_code(code) for code in _list(item.get("reasonCodes"))}
        )
        for item in candidates
    )
    execution_failure_count = sum(
        _safe_code(item.get("stageReached")) == "execution"
        and (
            _safe_code(item.get("status")) in {"blocked", "failure"}
            or "execution_failed" in {_safe_code(code) for code in _list(item.get("reasonCodes"))}
        )
        for item in candidates
    )

    funnel: list[dict[str, Any]] = []
    reached_by_stage: dict[str, int] = {}
    for index, stage in enumerate(STAGE_ORDER):
        reached = sum(
            (stage_index := _candidate_stage_index(item)) is not None and stage_index >= index
            for item in candidates
        )
        reached_by_stage[stage] = reached
        funnel.append(
            {
                "stage": stage,
                "reachedCount": reached,
                "reachRate": _ratio(reached, candidate_count),
            }
        )

    reason_counts: Counter[str] = Counter()
    for item in blocked:
        unique_codes = {
            code
            for raw in _list(item.get("reasonCodes"))[:8]
            if (code := _safe_code(raw)) and code != "redacted"
        }
        reason_counts.update(unique_codes)
    top_reasons = [
        {
            "code": code,
            "count": count,
            "shareOfBlockedCandidates": _ratio(count, blocked_count),
        }
        for code, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0]))[:MAX_TOP_REASONS]
    ]

    risk_reached = reached_by_stage.get("risk", 0)
    execution_reached = reached_by_stage.get("execution", 0)
    return {
        "size": size,
        "cyclesAvailable": len(selected),
        "metrics": {
            "candidateCount": candidate_count,
            "buyCount": buy_count,
            "blockedCount": blocked_count,
            "executedCount": executed_count,
            "riskRejectedCount": risk_rejected_count,
            "executionFailureCount": execution_failure_count,
        },
        "rates": {
            "buyRate": _ratio(buy_count, candidate_count),
            "blockedRate": _ratio(blocked_count, candidate_count),
            "executionRate": _ratio(executed_count, candidate_count),
            "riskRejectionRate": _ratio(risk_rejected_count, risk_reached),
            "executionFailureRate": _ratio(execution_failure_count, execution_reached),
        },
        "funnel": funnel,
        "topBlockingReasons": top_reasons,
    }


def _rate_delta_points(current: Mapping[str, Any], previous: Mapping[str, Any], key: str) -> float | None:
    current_rate = _number(_dict(current.get("rates")).get(key), 0, 1)
    previous_rate = _number(_dict(previous.get("rates")).get(key), 0, 1)
    if current_rate is None or previous_rate is None:
        return None
    return round((current_rate - previous_rate) * 100, 3)


def _trend(meaningful: list[dict[str, Any]]) -> dict[str, Any]:
    latest = _aggregate_window(meaningful[:6], 6)
    previous = _aggregate_window(meaningful[6:12], 6)
    enough_data = len(meaningful) >= 12
    if not enough_data:
        return {
            "comparison": "latest6_vs_previous6",
            "enoughData": False,
            "latestCycles": len(meaningful[:6]),
            "previousCycles": len(meaningful[6:12]),
            "candidateCountDelta": None,
            "blockedRateDeltaPoints": None,
            "executionRateDeltaPoints": None,
            "riskRejectionRateDeltaPoints": None,
        }
    return {
        "comparison": "latest6_vs_previous6",
        "enoughData": True,
        "latestCycles": 6,
        "previousCycles": 6,
        "candidateCountDelta": (
            latest["metrics"]["candidateCount"] - previous["metrics"]["candidateCount"]
        ),
        "blockedRateDeltaPoints": _rate_delta_points(latest, previous, "blockedRate"),
        "executionRateDeltaPoints": _rate_delta_points(latest, previous, "executionRate"),
        "riskRejectionRateDeltaPoints": _rate_delta_points(latest, previous, "riskRejectionRate"),
    }


def _consecutive_metadata_only(cycles: list[dict[str, Any]]) -> int:
    count = 0
    for cycle in cycles:
        if cycle.get("source") != "workflow_metadata":
            break
        count += 1
    return count


def _consecutive_stage_status(
    cycles: list[dict[str, Any]],
    stage_id: str,
    statuses: set[str],
) -> int:
    count = 0
    for cycle in cycles:
        summary = _dict(cycle.get("summary"))
        if _integer(summary.get("candidateCount")) <= 0:
            break
        stage = _stage_map(cycle).get(stage_id, {})
        if _safe_code(stage.get("status")) not in statuses:
            break
        count += 1
    return count


def _alert(
    code: str,
    severity: str,
    *,
    value: int | float | bool | None = None,
    threshold: int | float | None = None,
    window_cycles: int | None = None,
    observed_at: Any = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "status": "active",
        "value": value,
        "threshold": threshold,
        "windowCycles": window_cycles,
        "observedAt": _safe_text(observed_at, limit=48),
    }


def _build_alerts(
    snapshot: Mapping[str, Any],
    cycles: list[dict[str, Any]],
    meaningful: list[dict[str, Any]],
    window6: Mapping[str, Any],
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    generated_at = snapshot.get("generatedAt")
    risk = _dict(snapshot.get("risk"))
    emergency_halt = _dict(risk.get("emergencyHalt"))
    if emergency_halt.get("active") is True:
        alerts.append(_alert("emergency_halt_active", "critical", value=True, observed_at=emergency_halt.get("updatedAt") or generated_at))

    freshness = _dict(snapshot.get("freshness"))
    if freshness.get("isStale") is True:
        alerts.append(
            _alert(
                "snapshot_stale",
                "warning",
                value=_number(freshness.get("ageMinutes"), 0),
                threshold=_number(freshness.get("staleAfterMinutes"), 0),
                observed_at=generated_at,
            )
        )

    observability = _dict(snapshot.get("observability"))
    current = _dict(observability.get("current"))
    current_reason = _safe_code(current.get("reasonCode"))
    if current.get("source") == "workflow_metadata" and current_reason == "hourly_artifact_unavailable":
        alerts.append(_alert("hourly_artifact_unavailable", "warning", value=True, window_cycles=1, observed_at=current.get("observedAt") or generated_at))

    metadata_streak = _consecutive_metadata_only(cycles)
    if metadata_streak >= 3:
        alerts.append(_alert("consecutive_metadata_only_cycles", "warning", value=metadata_streak, threshold=3, window_cycles=metadata_streak, observed_at=generated_at))

    execution_failures = _integer(_dict(window6.get("metrics")).get("executionFailureCount"))
    if execution_failures > 0:
        alerts.append(_alert("recent_execution_failure", "critical", value=execution_failures, threshold=1, window_cycles=6, observed_at=generated_at))

    backtest_streak = _consecutive_stage_status(meaningful, "backtest", {"skipped", "not_attempted"})
    if backtest_streak >= 3:
        alerts.append(_alert("consecutive_no_backtest_progress", "warning", value=backtest_streak, threshold=3, window_cycles=backtest_streak, observed_at=generated_at))

    risk_streak = _consecutive_stage_status(meaningful, "risk", {"skipped", "not_attempted"})
    if risk_streak >= 3:
        alerts.append(_alert("consecutive_risk_not_attempted", "warning", value=risk_streak, threshold=3, window_cycles=risk_streak, observed_at=generated_at))

    funnel = {row.get("stage"): _dict(row) for row in _list(window6.get("funnel"))}
    risk_reached = _integer(funnel.get("risk", {}).get("reachedCount"))
    risk_rejection_rate = _number(_dict(window6.get("rates")).get("riskRejectionRate"), 0, 1)
    if risk_reached >= 3 and risk_rejection_rate is not None and risk_rejection_rate >= 0.5:
        alerts.append(_alert("high_risk_rejection_rate", "warning", value=risk_rejection_rate, threshold=0.5, window_cycles=6, observed_at=generated_at))

    if len(meaningful) < 6:
        alerts.append(_alert("insufficient_meaningful_history", "info", value=len(meaningful), threshold=6, window_cycles=len(meaningful), observed_at=generated_at))

    deduped: dict[str, dict[str, Any]] = {}
    for item in alerts:
        deduped.setdefault(item["code"], item)
    return sorted(
        deduped.values(),
        key=lambda item: (SEVERITY_ORDER.get(item["severity"], 99), item["code"]),
    )[:MAX_ALERTS]


def _latest_cycle(cycles: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not cycles:
        return None
    cycle = cycles[0]
    summary = _dict(cycle.get("summary"))
    return {
        "source": _safe_code(cycle.get("source")) or "unknown",
        "correlationId": _safe_text(cycle.get("correlationId")),
        "cycleId": _safe_text(cycle.get("cycleId")),
        "workflowRunId": _integer(cycle.get("workflowRunId"), 1) or None,
        "observedAt": _safe_text(cycle.get("observedAt"), limit=48),
        "status": _safe_code(cycle.get("status")) or "unknown",
        "reasonCode": _safe_code(cycle.get("reasonCode")),
        "summary": {
            "candidateCount": _integer(summary.get("candidateCount")),
            "buyCount": _integer(summary.get("buyCount")),
            "blockedCount": _integer(summary.get("blockedCount")),
            "executedCount": _integer(summary.get("executedCount")),
            "riskRejectedCount": _integer(summary.get("riskRejectedCount")),
            "executionFailureCount": _integer(summary.get("executionFailureCount")),
        },
    }


def build_analytics(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    history = _dict(snapshot.get("decisionHistory"))
    if history.get("schemaVersion") != HISTORY_SCHEMA_VERSION:
        raise ValueError("Phase 18 decision analytics requires decision-history.v1")
    if history.get("retentionCycles") != 24:
        raise ValueError("Phase 18 decision analytics requires 24-cycle bounded history")

    raw_cycles = [_dict(item) for item in _list(history.get("cycles"))[:24]]
    if not raw_cycles:
        raise ValueError("Phase 18 decision analytics requires at least one history cycle")
    if not all(_valid_cycle(cycle) for cycle in raw_cycles):
        raise ValueError("Phase 18 decision analytics requires seven-stage decision cycles")

    meaningful = _meaningful_cycles(raw_cycles)
    windows = [_aggregate_window(meaningful, size) for size in WINDOW_SIZES]
    window6 = windows[0]
    alerts = _build_alerts(snapshot, raw_cycles, meaningful, window6)
    overall_status = "healthy"
    if any(item["severity"] == "critical" for item in alerts):
        overall_status = "critical"
    elif any(item["severity"] == "warning" for item in alerts):
        overall_status = "warning"

    latest_meaningful = _latest_cycle(meaningful)
    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": _safe_text(snapshot.get("generatedAt"), limit=48),
        "sourceHistorySchemaVersion": HISTORY_SCHEMA_VERSION,
        "overallStatus": overall_status,
        "latest": _latest_cycle(raw_cycles),
        "latestMeaningful": latest_meaningful,
        "windows": windows,
        "trend": _trend(meaningful),
        "alerts": alerts,
        "dataQuality": {
            "historyCycles": len(raw_cycles),
            "meaningfulCycles": len(meaningful),
            "metadataOnlyCycles": sum(cycle.get("source") == "workflow_metadata" for cycle in raw_cycles),
            "latestCycleSource": _safe_code(raw_cycles[0].get("source")) or "unknown",
            "latestReasonCode": _safe_code(raw_cycles[0].get("reasonCode")),
            "latestMeaningfulObservedAt": latest_meaningful.get("observedAt") if latest_meaningful else None,
            "sufficientFor6CycleWindow": len(meaningful) >= 6,
            "sufficientForTrendComparison": len(meaningful) >= 12,
        },
    }


def enrich_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    payload = _dict(snapshot)
    if payload.get("schemaVersion") != "dashboard-snapshot.v2":
        raise ValueError("Phase 18 decision analytics requires dashboard-snapshot.v2")
    observability = _dict(payload.get("observability"))
    if observability.get("schemaVersion") != OBSERVABILITY_SCHEMA_VERSION:
        raise ValueError("Phase 18 decision analytics requires trading-observability.v1")
    payload["decisionAnalytics"] = build_analytics(payload)
    json.dumps(payload, allow_nan=False)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich dashboard snapshot with bounded decision analytics.")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    snapshot = _load(args.snapshot)
    enriched = enrich_snapshot(snapshot)
    output = args.output or args.snapshot
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    analytics = enriched["decisionAnalytics"]
    print(
        "Enriched decision analytics: "
        f"status={analytics['overallStatus']} "
        f"meaningful={analytics['dataQuality']['meaningfulCycles']} "
        f"alerts={len(analytics['alerts'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

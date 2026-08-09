#!/usr/bin/env python3
"""Publish a bounded, browser-safe trading decision observability projection."""
from __future__ import annotations

import argparse
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "trading-observability.v1"
FLOW_KIND = "decision_path"
STAGE_ORDER = (
    "scanner",
    "backtest",
    "market_regime",
    "portfolio",
    "profit",
    "risk",
    "execution",
)
MAX_CANDIDATES = 10
MAX_REASON_CODES = 8
SECRET_PATTERN = re.compile(
    r"(?i)(authorization|bearer\s+[a-z0-9._-]+|github[_-]?token|operator[_-]?token|"
    r"api[_-]?key|secret[_-]?key|password|database[_-]?(url|credentials?)|"
    r"ghp_[a-z0-9]+|github_pat_[a-z0-9_]+)"
)
STATUS_MAP = {
    "success": "success",
    "completed": "success",
    "ready": "success",
    "passed": "success",
    "warning": "warning",
    "partial": "warning",
    "degraded": "warning",
    "partial_failure": "warning",
    "blocked": "blocked",
    "block": "blocked",
    "rejected": "blocked",
    "risk_rejected": "blocked",
    "skipped": "skipped",
    "not_attempted": "not_attempted",
    "not_requested": "not_attempted",
    "failure": "failure",
    "failed": "failure",
    "error": "failure",
    "cancelled": "failure",
    "unknown": "unknown",
    "pending": "unknown",
    "running": "unknown",
}


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _first(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return default


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return _dict(value)


def _safe_text(value: Any, *, limit: int = 160) -> str | None:
    if value in (None, ""):
        return None
    text = " ".join(str(value).split())[:limit]
    if SECRET_PATTERN.search(text):
        return "redacted"
    return text or None


def _safe_code(value: Any) -> str | None:
    text = _safe_text(value, limit=96)
    if not text or text == "redacted":
        return text
    code = re.sub(r"[^a-zA-Z0-9_.:-]+", "_", text.strip()).strip("_").lower()
    return code[:96] or None


def _reason_codes(*values: Any) -> list[str]:
    result: list[str] = []
    for value in values:
        rows = value if isinstance(value, list) else [value]
        for row in rows:
            code = _safe_code(row)
            if code and code not in result:
                result.append(code)
            if len(result) >= MAX_REASON_CODES:
                return result
    return result


def _number(
    value: Any,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
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
    return round(parsed, 6)


def _iso(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _response_data(value: Mapping[str, Any]) -> dict[str, Any]:
    response = _dict(value.get("response"))
    data = _dict(response.get("data"))
    nested = _dict(data.get("data"))
    return nested or data


def _phase(snapshot: Mapping[str, Any], name: str) -> dict[str, Any]:
    for raw in _list(snapshot.get("phases")):
        row = _dict(raw)
        if str(row.get("name") or "").lower() == name:
            return row
    return {}


def _status(value: Any, default: str = "unknown") -> str:
    normalized = str(value or default).strip().lower()
    return STATUS_MAP.get(normalized, "unknown")


def _stage(
    stage_id: str,
    status: Any,
    *,
    reason_codes: list[str] | None = None,
    observed_at: Any = None,
    summary: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": stage_id,
        "status": _status(status),
        "reasonCodes": list(reason_codes or [])[:MAX_REASON_CODES],
        "observedAt": _iso(observed_at),
        "summary": dict(summary or {}),
    }


def _candidate_reason_codes(row: Mapping[str, Any]) -> list[str]:
    investability = _dict(row.get("investability_gate"))
    codes = _reason_codes(
        investability.get("rejection_codes"), investability.get("warning_codes")
    )
    if row.get("evidence_gate_passed") is False:
        codes = _reason_codes(codes, "evidence_gate_failed")
    classification = _safe_code(row.get("bucket_classification_status"))
    if row.get("allows_new_entry") is False:
        codes = _reason_codes(codes, "new_entry_not_allowed")
        if classification and classification not in {"classified", "success"}:
            codes = _reason_codes(codes, f"bucket_{classification}")
    verdict = _safe_code(row.get("final_verdict"))
    if verdict and verdict != "buy":
        codes = _reason_codes(codes, f"manager_verdict_{verdict}")
    return codes[:MAX_REASON_CODES]


def _candidate_status(
    row: Mapping[str, Any],
    backtests: Mapping[str, Mapping[str, Any]],
    risk_by_symbol: Mapping[str, Mapping[str, Any]],
    execution: Mapping[str, Any],
) -> tuple[str, str, list[str]]:
    symbol = str(row.get("symbol") or "").upper()
    reasons = _candidate_reason_codes(row)
    investability = _dict(row.get("investability_gate"))
    verdict = str(row.get("final_verdict") or "unknown").lower()
    if investability and investability.get("allowed") is False:
        return "blocked", "scanner", reasons
    if row.get("evidence_gate_passed") is False or row.get("allows_new_entry") is False:
        return "blocked", "scanner", reasons
    if verdict != "buy":
        return "not_selected", "scanner", reasons
    backtest = _dict(backtests.get(symbol))
    if backtest:
        backtest_status = str(backtest.get("status") or "unknown").lower()
        if backtest_status in {"no_eligible_strategy", "failed", "failure", "error"}:
            return "blocked", "backtest", _reason_codes(reasons, backtest_status)
        if backtest_status == "eligible_strategy_found":
            risk = _dict(risk_by_symbol.get(symbol))
            if risk:
                approved = risk.get("approved")
                risk_status = str(
                    _first(risk.get("status"), risk.get("decision"), default="")
                ).lower()
                if approved is False or risk_status in {
                    "rejected",
                    "risk_rejected",
                    "blocked",
                    "denied",
                }:
                    return (
                        "blocked",
                        "risk",
                        _reason_codes(
                            reasons,
                            _first(
                                risk.get("reason_code"),
                                risk.get("reason"),
                                "risk_rejected",
                            ),
                        ),
                    )
                if approved is True or risk_status in {"approved", "success", "allowed"}:
                    execution_status = str(execution.get("status") or "").lower()
                    if execution_status in {
                        "submitted",
                        "executed",
                        "success",
                        "filled",
                        "partial_fill",
                    }:
                        return (
                            "executed",
                            "execution",
                            _reason_codes(reasons, execution.get("reason")),
                        )
                    if execution_status in {"failed", "failure", "error"}:
                        return (
                            "blocked",
                            "execution",
                            _reason_codes(
                                reasons, execution.get("reason"), "execution_failed"
                            ),
                        )
                    return "approved", "risk", reasons
            return "backtest_passed", "backtest", reasons
    return "eligible", "scanner", reasons


def build_candidates(
    discovery: Mapping[str, Any], backtest_report: Mapping[str, Any]
) -> list[dict[str, Any]]:
    data = _response_data(discovery)
    backtest_data = _dict(backtest_report.get("data"))
    backtests = {
        str(_dict(item).get("symbol") or "").upper(): _dict(item)
        for item in _list(backtest_data.get("items"))
        if _dict(item).get("symbol")
    }
    risk_by_symbol: dict[str, Mapping[str, Any]] = {}
    for raw in _list(data.get("risk_approvals")):
        item = _dict(raw)
        symbol = str(item.get("symbol") or "").upper()
        if symbol:
            risk_by_symbol[symbol] = item
    execution = _dict(data.get("execution"))
    output: list[dict[str, Any]] = []
    for raw in _list(data.get("ranked_candidates"))[:MAX_CANDIDATES]:
        row = _dict(raw)
        symbol = _safe_text(row.get("symbol"), limit=16)
        if not symbol:
            continue
        state, stage_reached, reasons = _candidate_status(
            row, backtests, risk_by_symbol, execution
        )
        score = _dict(row.get("score_breakdown"))
        output.append(
            {
                "symbol": symbol.upper(),
                "rank": int(
                    _number(row.get("rank"), 1, 10_000) or len(output) + 1
                ),
                "verdict": _safe_code(row.get("final_verdict")) or "unknown",
                "finalScore": _number(
                    score.get("final_opportunity_score"), 0, 1
                ),
                "strategyBucket": _safe_code(
                    _first(
                        row.get("strategy_bucket"), row.get("proposed_strategy_bucket")
                    )
                )
                or "unassigned",
                "status": state,
                "stageReached": stage_reached,
                "reasonCodes": reasons,
            }
        )
    return output


def build_stages(
    snapshot: Mapping[str, Any], artifact_dir: Path
) -> list[dict[str, Any]]:
    generated = snapshot.get("generatedAt")
    cycle = _dict(snapshot.get("cycle"))
    discovery = _load(artifact_dir / "hourly-pre-backtest-discovery.json")
    discovery_data = _response_data(discovery)
    review = _load(artifact_dir / "hourly-position-review.json")
    manager = _load(artifact_dir / "hourly-manager-cycle.json")
    manager_data = _response_data(_dict(manager.get("manager_response")))
    backtest = _load(artifact_dir / "hourly-backtest-result.json")
    backtest_items = [
        _dict(item) for item in _list(_dict(backtest.get("data")).get("items"))
    ]

    scanner_phase = _phase(snapshot, "scanner")
    scanner_count = int(
        _number(
            _first(discovery_data.get("scanner_count"), cycle.get("candidateCount")),
            0,
            1_000_000,
        )
        or 0
    )
    scanner_status = _first(
        discovery.get("status"),
        scanner_phase.get("status"),
        "skipped" if not discovery else "unknown",
    )
    scanner_reasons = _reason_codes(
        scanner_phase.get("message"), "no_candidates" if scanner_count == 0 else None
    )

    backtest_phase = _phase(snapshot, "backtest")
    eligible_count = sum(
        1
        for item in backtest_items
        if str(item.get("status") or "") == "eligible_strategy_found"
    )
    attempted_count = len(backtest_items)
    if attempted_count:
        backtest_status = "success" if eligible_count else "blocked"
        backtest_reasons = [] if eligible_count else ["no_eligible_strategy"]
    else:
        backtest_status = _first(backtest_phase.get("status"), "skipped")
        backtest_reasons = _reason_codes(
            backtest_phase.get("message"),
            cycle.get("executionReason")
            if backtest_status in {"skipped", "not_attempted"}
            else None,
        )

    regime = _dict(review.get("market_regime"))
    regime_status = "success" if regime else "not_attempted"
    regime_summary = {
        "regime": _safe_code(regime.get("regime")) if regime else None,
        "riskLevel": _safe_code(regime.get("risk_level")) if regime else None,
        "confidence": _number(regime.get("confidence_score"), 0, 1)
        if regime
        else None,
    }

    portfolio_status = (
        "success"
        if review and review.get("safe_for_candidate_analysis") is not False
        else ("warning" if review else "not_attempted")
    )
    position_decisions = [_dict(item) for item in _list(review.get("position_decisions"))]
    portfolio_reasons = _reason_codes(
        "protection_gap_detected"
        if review and review.get("safe_for_candidate_analysis") is False
        else None
    )

    if position_decisions:
        profit_status = "success"
        counts: dict[str, int] = {}
        for row in position_decisions:
            action = _safe_code(row.get("action")) or "unknown"
            counts[action] = counts.get(action, 0) + 1
        profit_summary: dict[str, Any] = {
            "reviewedPositions": len(position_decisions),
            "actionCounts": counts,
        }
    else:
        profit_status = "skipped" if review else "not_attempted"
        profit_summary = {"reviewedPositions": 0, "actionCounts": {}}

    risk_phase = _phase(snapshot, "risk")
    risk_approvals = [
        _dict(item)
        for item in _list(
            _first(
                discovery_data.get("risk_approvals"),
                manager_data.get("risk_approvals"),
                default=[],
            )
        )
    ]
    rejected_count = sum(
        1
        for item in risk_approvals
        if item.get("approved") is False
        or str(item.get("status") or item.get("decision") or "").lower()
        in {"rejected", "risk_rejected", "blocked", "denied"}
    )
    risk_status = (
        "blocked"
        if rejected_count
        else _first(
            risk_phase.get("status"),
            "success" if risk_approvals else "not_attempted",
        )
    )
    risk_reasons = _reason_codes(
        risk_phase.get("message"), "risk_rejected" if rejected_count else None
    )

    execution_phase = _phase(snapshot, "execution")
    execution = _dict(
        _first(
            manager_data.get("execution"),
            _dict(manager.get("manager_response")).get("execution"),
            default={},
        )
    )
    execution_status_raw = _first(
        execution.get("status"),
        cycle.get("executionStatus"),
        execution_phase.get("status"),
        "not_attempted",
    )
    execution_status = _status(execution_status_raw)
    if str(execution_status_raw).lower() in {
        "submitted",
        "executed",
        "filled",
        "partial_fill",
    }:
        execution_status = (
            "warning"
            if str(execution_status_raw).lower() == "partial_fill"
            else "success"
        )
    execution_reasons = _reason_codes(
        execution.get("reason"),
        cycle.get("executionReason"),
        execution_phase.get("message"),
    )

    return [
        _stage(
            "scanner",
            scanner_status,
            reason_codes=scanner_reasons,
            observed_at=_first(discovery.get("generated_at"), generated),
            summary={"candidateCount": scanner_count},
        ),
        _stage(
            "backtest",
            backtest_status,
            reason_codes=backtest_reasons,
            observed_at=generated,
            summary={
                "attemptedCount": attempted_count,
                "eligibleCount": eligible_count,
            },
        ),
        _stage(
            "market_regime",
            regime_status,
            observed_at=_first(review.get("generated_at"), generated),
            summary=regime_summary,
        ),
        _stage(
            "portfolio",
            portfolio_status,
            reason_codes=portfolio_reasons,
            observed_at=_first(review.get("generated_at"), generated),
            summary={
                "positionDecisionCount": len(position_decisions),
                "safeForCandidateAnalysis": review.get("safe_for_candidate_analysis")
                if review
                else None,
            },
        ),
        _stage(
            "profit",
            profit_status,
            observed_at=_first(review.get("generated_at"), generated),
            summary=profit_summary,
        ),
        _stage(
            "risk",
            risk_status,
            reason_codes=risk_reasons,
            observed_at=generated,
            summary={
                "approvalCount": len(risk_approvals),
                "rejectedCount": rejected_count,
            },
        ),
        _stage(
            "execution",
            execution_status,
            reason_codes=execution_reasons,
            observed_at=generated,
            summary={
                "attempted": bool(cycle.get("executionAttempted")),
                "partialFill": bool(cycle.get("partialFillDetected")),
            },
        ),
    ]


def _has_meaningful_artifact(artifact_dir: Path) -> bool:
    return any(
        (artifact_dir / name).exists()
        for name in (
            "hourly-preflight.json",
            "hourly-position-review.json",
            "hourly-pre-backtest-discovery.json",
            "hourly-manager-cycle.json",
            "hourly-backtest-result.json",
        )
    )


def build_cycle(
    snapshot: Mapping[str, Any], artifact_dir: Path, *, source: str
) -> dict[str, Any]:
    preflight = _load(artifact_dir / "hourly-preflight.json")
    discovery = _load(artifact_dir / "hourly-pre-backtest-discovery.json")
    cycle = _dict(snapshot.get("cycle"))
    workflow = _dict(snapshot.get("workflow"))
    correlation_id = _safe_text(
        _first(
            preflight.get("correlation_id"),
            preflight.get("portfolio_cycle_id"),
            cycle.get("id"),
        ),
        limit=96,
    )
    cycle_id = _safe_text(
        _first(cycle.get("id"), preflight.get("portfolio_cycle_id")), limit=96
    )
    reason_code = _safe_code(
        _first(cycle.get("executionReason"), _phase(snapshot, "execution").get("message"))
    )
    return {
        "source": source,
        "flowKind": FLOW_KIND,
        "correlationId": correlation_id,
        "cycleId": cycle_id,
        "workflowRunId": int(_number(workflow.get("runId"), 1, 10**15) or 0)
        or None,
        "observedAt": _iso(
            _first(snapshot.get("generatedAt"), discovery.get("generated_at"))
        ),
        "status": _safe_code(cycle.get("status")) or "unknown",
        "reasonCode": reason_code,
        "stages": build_stages(snapshot, artifact_dir),
        "candidates": build_candidates(
            discovery, _load(artifact_dir / "hourly-backtest-result.json")
        ),
    }


def _metadata_cycle(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    cycle = _dict(snapshot.get("cycle"))
    workflow = _dict(snapshot.get("workflow"))
    reason = _safe_code(cycle.get("executionReason"))
    stages = []
    for stage_id in STAGE_ORDER:
        status = "skipped" if stage_id in {"scanner", "backtest"} else "not_attempted"
        stages.append(
            _stage(
                stage_id,
                status,
                reason_codes=_reason_codes(reason),
                observed_at=snapshot.get("generatedAt"),
                summary={},
            )
        )
    return {
        "source": "workflow_metadata",
        "flowKind": FLOW_KIND,
        "correlationId": _safe_text(cycle.get("id"), limit=96),
        "cycleId": _safe_text(cycle.get("id"), limit=96),
        "workflowRunId": int(_number(workflow.get("runId"), 1, 10**15) or 0)
        or None,
        "observedAt": _iso(snapshot.get("generatedAt")),
        "status": _safe_code(cycle.get("status")) or "unknown",
        "reasonCode": reason,
        "stages": stages,
        "candidates": [],
    }


def build_observability(
    snapshot: Mapping[str, Any], artifact_dir: Path, previous: Mapping[str, Any]
) -> dict[str, Any]:
    meaningful = _has_meaningful_artifact(artifact_dir)
    current = (
        build_cycle(snapshot, artifact_dir, source="hourly_artifact")
        if meaningful
        else _metadata_cycle(snapshot)
    )
    previous_obs = _dict(previous.get("observability"))
    previous_last = _dict(previous_obs.get("lastMeaningful"))
    previous_current = _dict(previous_obs.get("current"))
    if meaningful:
        last_meaningful = current
    elif previous_last:
        last_meaningful = previous_last
    elif previous_current.get("source") == "hourly_artifact":
        last_meaningful = previous_current
    else:
        last_meaningful = None
    return {
        "schemaVersion": SCHEMA_VERSION,
        "current": current,
        "lastMeaningful": last_meaningful,
    }


def enrich_snapshot(
    snapshot: Mapping[str, Any],
    artifact_dir: Path,
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = _dict(snapshot)
    if payload.get("schemaVersion") != "dashboard-snapshot.v2":
        raise ValueError("Phase 16 trading observability requires dashboard-snapshot.v2")
    payload["observability"] = build_observability(
        payload, artifact_dir, _dict(previous)
    )
    json.dumps(payload, allow_nan=False)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enrich dashboard-snapshot.v2 with safe trading decision observability."
    )
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    snapshot = _load(args.snapshot)
    previous = _load(args.previous) if args.previous else {}
    enriched = enrich_snapshot(snapshot, args.artifact_dir, previous)
    output = args.output or args.snapshot
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    current = enriched["observability"]["current"]
    print(
        "Enriched trading observability: "
        f"source={current['source']} stages={len(current['stages'])} "
        f"candidates={len(current['candidates'])}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

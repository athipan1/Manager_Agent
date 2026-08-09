#!/usr/bin/env python3
"""Publish bounded browser-safe historical trading decision observability."""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "decision-history.v1"
OBSERVABILITY_SCHEMA_VERSION = "trading-observability.v1"
FLOW_KIND = "decision_path"
MAX_CYCLES = 24
MAX_CANDIDATES = 10
MAX_REASON_CODES = 8
STAGE_ORDER = (
    "scanner",
    "backtest",
    "market_regime",
    "portfolio",
    "profit",
    "risk",
    "execution",
)
SECRET_PATTERN = re.compile(
    r"(?i)(authorization|bearer\s+[a-z0-9._-]+|github[_-]?token|operator[_-]?token|"
    r"api[_-]?key|secret[_-]?key|password|database[_-]?(url|credentials?)|"
    r"client[_-]?order[_-]?id|ghp_[a-z0-9]+|github_pat_[a-z0-9_]+)"
)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _load(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
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
    return round(parsed, 6)


def _reason_codes(value: Any) -> list[str]:
    output: list[str] = []
    for raw in _list(value):
        code = _safe_code(raw)
        if code and code not in output:
            output.append(code)
        if len(output) >= MAX_REASON_CODES:
            break
    return output


def _safe_public_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 2:
        return None
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, str):
        return _safe_text(value)
    if isinstance(value, list):
        return [_safe_public_value(item, depth=depth + 1) for item in value[:16]]
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, item in list(value.items())[:24]:
            safe_key = _safe_code(key)
            if not safe_key or safe_key == "redacted":
                continue
            output[safe_key] = _safe_public_value(item, depth=depth + 1)
        return output
    return None


def _response_data(value: Mapping[str, Any]) -> dict[str, Any]:
    response = _dict(value.get("response"))
    data = _dict(response.get("data"))
    nested = _dict(data.get("data"))
    return nested or data


def _extract_candidate_refs(artifact_dir: Path | None) -> dict[str, dict[str, str | None]]:
    if not artifact_dir:
        return {}
    discovery = _load(artifact_dir / "hourly-pre-backtest-discovery.json")
    data = _response_data(discovery)
    risks = {
        str(_dict(item).get("symbol") or "").upper(): _dict(item)
        for item in _list(data.get("risk_approvals"))
        if _dict(item).get("symbol")
    }
    refs: dict[str, dict[str, str | None]] = {}
    for raw in _list(data.get("ranked_candidates"))[:MAX_CANDIDATES]:
        row = _dict(raw)
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        risk = risks.get(symbol, {})
        decision_id = _safe_text(
            row.get("decision_id") or row.get("decisionId") or risk.get("decision_id") or risk.get("decisionId"),
            limit=96,
        )
        position_id = _safe_text(
            row.get("position_id") or row.get("positionId") or risk.get("position_id") or risk.get("positionId"),
            limit=96,
        )
        refs[symbol] = {"decisionId": decision_id, "positionId": position_id}
    return refs


def _sanitize_stage(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    stage_id = _safe_code(raw.get("id"))
    if stage_id not in STAGE_ORDER:
        return None
    return {
        "id": stage_id,
        "status": _safe_code(raw.get("status")) or "unknown",
        "reasonCodes": _reason_codes(raw.get("reasonCodes")),
        "observedAt": _safe_text(raw.get("observedAt"), limit=48),
        "summary": _safe_public_value(_dict(raw.get("summary"))),
    }


def _sanitize_candidate(raw: Mapping[str, Any], refs: Mapping[str, Mapping[str, Any]]) -> dict[str, Any] | None:
    symbol = (_safe_text(raw.get("symbol"), limit=16) or "").upper()
    if not symbol or not re.fullmatch(r"[A-Z0-9.-]{1,16}", symbol):
        return None
    row_refs = _dict(refs.get(symbol))
    existing_refs = _dict(raw.get("refs"))
    decision_id = _safe_text(row_refs.get("decisionId") or existing_refs.get("decisionId"), limit=96)
    position_id = _safe_text(row_refs.get("positionId") or existing_refs.get("positionId"), limit=96)
    stage_reached = _safe_code(raw.get("stageReached"))
    return {
        "symbol": symbol,
        "rank": int(_number(raw.get("rank"), 1, 10_000) or 0) or None,
        "verdict": _safe_code(raw.get("verdict")) or "unknown",
        "finalScore": _number(raw.get("finalScore"), 0, 1),
        "strategyBucket": _safe_code(raw.get("strategyBucket")) or "unassigned",
        "status": _safe_code(raw.get("status")) or "unknown",
        "stageReached": stage_reached if stage_reached in STAGE_ORDER else None,
        "reasonCodes": _reason_codes(raw.get("reasonCodes")),
        "refs": {"decisionId": decision_id, "positionId": position_id},
    }


def _cycle_summary(candidates: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "candidateCount": len(candidates),
        "buyCount": sum(item.get("verdict") == "buy" for item in candidates),
        "blockedCount": sum(item.get("status") == "blocked" for item in candidates),
        "executedCount": sum(item.get("status") == "executed" for item in candidates),
        "riskRejectedCount": sum(
            item.get("status") == "blocked" and item.get("stageReached") == "risk"
            for item in candidates
        ),
        "executionFailureCount": sum(
            item.get("status") == "blocked" and item.get("stageReached") == "execution"
            for item in candidates
        ),
    }


def _sanitize_cycle(raw: Mapping[str, Any], refs: Mapping[str, Mapping[str, Any]] | None = None) -> dict[str, Any] | None:
    row = _dict(raw)
    if row.get("flowKind") not in (None, FLOW_KIND):
        return None
    stages_by_id: dict[str, dict[str, Any]] = {}
    for raw_stage in _list(row.get("stages")):
        stage = _sanitize_stage(_dict(raw_stage))
        if stage:
            stages_by_id[stage["id"]] = stage
    stages = [stages_by_id[stage_id] for stage_id in STAGE_ORDER if stage_id in stages_by_id]
    if len(stages) != len(STAGE_ORDER):
        return None
    candidates: list[dict[str, Any]] = []
    for raw_candidate in _list(row.get("candidates"))[:MAX_CANDIDATES]:
        candidate = _sanitize_candidate(_dict(raw_candidate), refs or {})
        if candidate:
            candidates.append(candidate)
    return {
        "source": _safe_code(row.get("source")) or "unknown",
        "flowKind": FLOW_KIND,
        "correlationId": _safe_text(row.get("correlationId"), limit=96),
        "cycleId": _safe_text(row.get("cycleId"), limit=96),
        "workflowRunId": int(_number(row.get("workflowRunId"), 1, 10**15) or 0) or None,
        "observedAt": _safe_text(row.get("observedAt"), limit=48),
        "status": _safe_code(row.get("status")) or "unknown",
        "reasonCode": _safe_code(row.get("reasonCode")),
        "summary": _cycle_summary(candidates),
        "stages": stages,
        "candidates": candidates,
    }


def _cycle_key(cycle: Mapping[str, Any]) -> str | None:
    for key in ("cycleId", "correlationId"):
        value = _safe_text(cycle.get(key), limit=96)
        if value:
            return f"{key}:{value}"
    if cycle.get("workflowRunId"):
        return f"workflowRunId:{cycle['workflowRunId']}"
    observed = _safe_text(cycle.get("observedAt"), limit=48)
    return f"observedAt:{observed}" if observed else None


def build_history(
    snapshot: Mapping[str, Any],
    previous: Mapping[str, Any],
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    observability = _dict(snapshot.get("observability"))
    if observability.get("schemaVersion") != OBSERVABILITY_SCHEMA_VERSION:
        raise ValueError("Phase 17 decision history requires trading-observability.v1")

    refs = _extract_candidate_refs(artifact_dir)
    previous_history = _dict(previous.get("decisionHistory"))
    previous_observability = _dict(previous.get("observability"))
    candidates = [
        (observability.get("current"), refs),
        (observability.get("lastMeaningful"), refs),
        *[(item, {}) for item in _list(previous_history.get("cycles"))],
        (previous_observability.get("current"), {}),
        (previous_observability.get("lastMeaningful"), {}),
    ]

    cycles: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw, row_refs in candidates:
        cycle = _sanitize_cycle(_dict(raw), row_refs)
        if not cycle:
            continue
        key = _cycle_key(cycle)
        if not key or key in seen:
            continue
        seen.add(key)
        cycles.append(cycle)
        if len(cycles) >= MAX_CYCLES:
            break

    return {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": _safe_text(snapshot.get("generatedAt"), limit=48),
        "retentionCycles": MAX_CYCLES,
        "cycles": cycles,
    }


def enrich_snapshot(
    snapshot: Mapping[str, Any],
    previous: Mapping[str, Any] | None = None,
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    payload = _dict(snapshot)
    if payload.get("schemaVersion") != "dashboard-snapshot.v2":
        raise ValueError("Phase 17 decision history requires dashboard-snapshot.v2")
    payload["decisionHistory"] = build_history(payload, _dict(previous), artifact_dir)
    json.dumps(payload, allow_nan=False)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Enrich dashboard snapshot with bounded decision history.")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--artifact-dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    snapshot = _load(args.snapshot)
    previous = _load(args.previous)
    enriched = enrich_snapshot(snapshot, previous, args.artifact_dir)
    output = args.output or args.snapshot
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(enriched, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    history = enriched["decisionHistory"]
    print(f"Enriched decision history: cycles={len(history['cycles'])}/{history['retentionCycles']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

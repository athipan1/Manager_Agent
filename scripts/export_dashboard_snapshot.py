from __future__ import annotations

import argparse
import json
import math
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = "dashboard-snapshot.v2"
PRIVACY_MODES = {"full", "masked", "status-only"}
TOP_LEVEL_KEYS = {
    "schemaVersion",
    "generatedAt",
    "workflow",
    "runtime",
    "cycle",
    "phases",
    "account",
    "summary",
    "positions",
    "openOrders",
    "signals",
    "warnings",
    "error",
    "lastSuccessfulRun",
    "freshness",
    "privacy",
}
PHASE_NAMES = (
    "preflight",
    "portfolio_review",
    "protection_reconciliation",
    "scanner",
    "backtest",
    "risk",
    "execution",
    "final_reconciliation",
)
PHASE_STATUSES = {
    "pending",
    "running",
    "success",
    "warning",
    "skipped",
    "not_attempted",
    "failure",
    "cancelled",
    "unknown",
}
SECRET_PATTERN = re.compile(
    r"(?i)(authorization|bearer\s+[a-z0-9._-]+|github[_-]?token|operator[_-]?token|"
    r"api[_-]?key|secret[_-]?key|password|database[_-]?(url|credentials?)|ghp_[a-z0-9]+|github_pat_[a-z0-9_]+)"
)


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _first(*values: Any, default: Any = None) -> Any:
    for value in values:
        if value not in (None, ""):
            return value
    return default


def _finite_number(value: Any, default: float | None = None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if math.isfinite(parsed) else default


def _integer(value: Any, default: int = 0) -> int:
    number = _finite_number(value)
    return int(number) if number is not None else default


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _utc_datetime(value: Any, *, fallback: datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            parsed = fallback or datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_z(value: Any, *, fallback: datetime | None = None) -> str:
    return _utc_datetime(value, fallback=fallback).isoformat().replace("+00:00", "Z")


def _sanitize_text(value: Any, *, limit: int = 280) -> str | None:
    if value in (None, ""):
        return None
    text = " ".join(str(value).split())[:limit]
    if SECRET_PATTERN.search(text):
        return "Sensitive diagnostic details were redacted."
    return text


def _unwrap_data(value: Any) -> Any:
    if isinstance(value, Mapping) and "data" in value:
        return value.get("data")
    return value


def _response_data(report: Mapping[str, Any]) -> dict[str, Any]:
    response = _dict(report.get("response"))
    data = _dict(response.get("data"))
    nested = _dict(data.get("data"))
    return nested or data


def _safe_position(row: Mapping[str, Any], *, masked: bool) -> dict[str, Any]:
    protection = _dict(row.get("protection"))
    item = {
        "symbol": _sanitize_text(row.get("symbol"), limit=16) or "UNKNOWN",
        "quantity": _finite_number(_first(row.get("quantity"), row.get("qty"))),
        "averageCost": _finite_number(_first(row.get("averageCost"), row.get("average_cost"), row.get("avg_entry_price"))),
        "currentPrice": _finite_number(_first(row.get("currentPrice"), row.get("current_market_price"), row.get("current_price"))),
        "marketValue": _finite_number(_first(row.get("marketValue"), row.get("market_value"))),
        "unrealizedPnL": _finite_number(_first(row.get("unrealizedPnL"), row.get("unrealized_pl"))),
        "bucket": _sanitize_text(_first(row.get("bucket"), row.get("strategy_bucket"), default="unassigned"), limit=48),
        "protection": {
            "status": _sanitize_text(_first(protection.get("status"), row.get("protection_status"), default="unknown"), limit=48),
            "hasStopLoss": _bool(_first(protection.get("hasStopLoss"), row.get("has_protective_stop"), default=False)),
            "hasTakeProfit": _bool(_first(protection.get("hasTakeProfit"), row.get("has_take_profit"), default=False)),
            "hasBracket": _bool(_first(protection.get("hasBracket"), row.get("has_bracket"), default=False)),
        },
        "valuesMasked": masked,
    }
    if masked:
        for key in ("quantity", "averageCost", "currentPrice", "marketValue", "unrealizedPnL"):
            item[key] = None
    return item


def _safe_order(row: Mapping[str, Any], *, masked: bool) -> dict[str, Any]:
    item = {
        "symbol": _sanitize_text(row.get("symbol"), limit=16) or "UNKNOWN",
        "side": _sanitize_text(row.get("side"), limit=16) or "unknown",
        "quantity": _finite_number(_first(row.get("quantity"), row.get("qty"))),
        "orderClass": _sanitize_text(_first(row.get("orderClass"), row.get("order_class"), default="unknown"), limit=32),
        "type": _sanitize_text(_first(row.get("type"), row.get("order_type"), default="unknown"), limit=32),
        "status": _sanitize_text(_first(row.get("status"), row.get("broker_status"), default="unknown"), limit=32),
        "takeProfit": _finite_number(_first(row.get("takeProfit"), row.get("take_profit"), row.get("limit_price"), row.get("price"))),
        "stopLoss": _bool(_first(row.get("stopLoss"), row.get("stop_loss"), row.get("stop_price"), default=False)),
        "valuesMasked": masked,
    }
    if masked:
        item["quantity"] = None
        item["takeProfit"] = None
    return item


def _safe_signal(row: Mapping[str, Any]) -> dict[str, Any]:
    execution = _dict(row.get("execution"))
    output = _dict(execution.get("output"))
    return {
        "symbol": _sanitize_text(row.get("symbol"), limit=16) or "UNKNOWN",
        "status": _sanitize_text(_first(row.get("status"), execution.get("execution_status"), default="unknown"), limit=32),
        "skill": _sanitize_text(_first(row.get("skill"), row.get("skill_name"), row.get("skill_id"), default="signal"), limit=80),
        "signal": _sanitize_text(_first(row.get("signal"), output.get("signal"), output.get("reason"), row.get("reason"), default="-"), limit=160),
        "confidence": _finite_number(_first(row.get("confidence"), row.get("confidence_score"), output.get("confidence"))),
    }


def _normalize_phase(row: Mapping[str, Any]) -> dict[str, Any]:
    name = str(row.get("name") or "unknown").strip().lower()
    status = str(row.get("status") or "unknown").strip().lower()
    return {
        "name": name if name in PHASE_NAMES else "unknown",
        "status": status if status in PHASE_STATUSES else "unknown",
        "message": _sanitize_text(row.get("message")),
    }


def _workflow(report: Mapping[str, Any], metadata: Mapping[str, Any], generated_at: str) -> dict[str, Any]:
    source = {**_dict(report.get("workflow")), **_dict(metadata)}
    started_at = source.get("startedAt") or source.get("started_at")
    completed_at = source.get("completedAt") or source.get("completed_at") or generated_at
    duration = _finite_number(source.get("durationSeconds"))
    if duration is None and started_at and completed_at:
        duration = max(0.0, (_utc_datetime(completed_at) - _utc_datetime(started_at)).total_seconds())
    return {
        "runId": _integer(_first(source.get("runId"), source.get("run_id")), default=0) or None,
        "runNumber": _integer(_first(source.get("runNumber"), source.get("run_number")), default=0) or None,
        "runUrl": _sanitize_text(_first(source.get("runUrl"), source.get("run_url")), limit=300),
        "eventName": _sanitize_text(_first(source.get("eventName"), source.get("event_name"), default="unknown"), limit=40),
        "status": _sanitize_text(_first(source.get("status"), default="completed"), limit=24) or "completed",
        "conclusion": _sanitize_text(_first(source.get("conclusion"), default="unknown"), limit=32) or "unknown",
        "startedAt": _iso_z(started_at, fallback=_utc_datetime(generated_at)) if started_at else None,
        "completedAt": _iso_z(completed_at, fallback=_utc_datetime(generated_at)),
        "durationSeconds": round(duration, 3) if duration is not None else None,
    }


def _fallback_error(conclusion: str, malformed: bool = False) -> dict[str, str]:
    if malformed:
        return {"code": "MALFORMED_HOURLY_ARTIFACT", "message": "Hourly artifact was missing or invalid; workflow metadata fallback is shown."}
    if conclusion == "cancelled":
        return {"code": "HOURLY_WORKFLOW_CANCELLED", "message": "Hourly Auto Trading was cancelled before completion."}
    return {"code": "HOURLY_WORKFLOW_FAILED", "message": "Hourly Auto Trading did not complete successfully."}


def build_snapshot(
    report: Mapping[str, Any] | None,
    *,
    workflow_metadata: Mapping[str, Any] | None = None,
    previous_snapshot: Mapping[str, Any] | None = None,
    privacy_mode: str = "masked",
    now: datetime | None = None,
    expected_interval_minutes: int = 60,
    stale_after_minutes: int = 120,
    malformed_artifact: bool = False,
) -> dict[str, Any]:
    if privacy_mode not in PRIVACY_MODES:
        raise ValueError(f"Unsupported privacy mode: {privacy_mode}")
    current_time = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    report = _dict(report)
    previous_snapshot = _dict(previous_snapshot)
    generated_at = _iso_z(_first(report.get("generatedAt"), report.get("generated_at")), fallback=current_time)
    workflow = _workflow(report, workflow_metadata or {}, generated_at)
    response = _response_data(report)
    runtime_source = _dict(report.get("runtime"))
    request = _dict(report.get("request"))
    cycle_source = _dict(report.get("cycle"))
    candidate_cycle = _dict(report.get("candidate_cycle"))
    execution = _dict(_first(cycle_source.get("execution"), response.get("execution"), candidate_cycle.get("execution"), default={}))

    broker_snapshot = _dict(report.get("broker_snapshot"))
    portfolio = _dict(_unwrap_data(broker_snapshot.get("portfolio")))
    account_source = _dict(report.get("account")) or _dict(_unwrap_data(broker_snapshot.get("account"))) or _dict(portfolio.get("account"))
    positions_source = _list(report.get("positions")) or _list(_unwrap_data(broker_snapshot.get("positions"))) or _list(portfolio.get("positions"))
    orders_source = _list(report.get("openOrders")) or _list(report.get("open_orders")) or _list(_unwrap_data(broker_snapshot.get("orders"))) or _list(portfolio.get("open_orders"))
    signals_source = _list(report.get("signals")) or _list(report.get("curatorSignals")) or _list(response.get("curator_signals"))

    privacy_masked = privacy_mode != "full"
    status_only = privacy_mode == "status-only"
    positions = [] if status_only else [_safe_position(row, masked=privacy_masked) for row in positions_source if isinstance(row, Mapping)]
    open_orders = [] if status_only else [_safe_order(row, masked=privacy_masked) for row in orders_source if isinstance(row, Mapping)]
    signals = [] if status_only else [_safe_signal(row) for row in signals_source if isinstance(row, Mapping)]

    account = {
        "cash": _finite_number(_first(account_source.get("cash"), account_source.get("cash_balance"))),
        "equity": _finite_number(_first(account_source.get("equity"), account_source.get("portfolio_value"))),
        "buyingPower": _finite_number(_first(account_source.get("buyingPower"), account_source.get("buying_power"))),
        "status": _sanitize_text(account_source.get("status"), limit=40),
        "lastSyncedAt": _iso_z(_first(account_source.get("lastSyncedAt"), account_source.get("last_synced_at"), generated_at), fallback=current_time),
        "valuesMasked": privacy_masked,
    }
    if privacy_masked:
        account.update({"cash": None, "equity": None, "buyingPower": None})

    selected_symbols = cycle_source.get("selectedSymbols") or cycle_source.get("selected_symbols") or response.get("top_10_symbols") or []
    if not isinstance(selected_symbols, list):
        selected_symbols = []
    candidate_count = _integer(_first(cycle_source.get("candidateCount"), cycle_source.get("candidate_count"), response.get("scanner_count"), len(selected_symbols)))
    execution_status = _sanitize_text(_first(cycle_source.get("executionStatus"), execution.get("status"), default="not_attempted"), limit=48) or "not_attempted"
    execution_reason = _sanitize_text(_first(cycle_source.get("executionReason"), execution.get("reason")), limit=200)
    cycle_status = _sanitize_text(_first(cycle_source.get("status"), report.get("cycle_status"), default="unknown"), limit=32) or "unknown"
    if workflow["conclusion"] in {"failure", "cancelled", "timed_out", "action_required", "stale"}:
        cycle_status = "cancelled" if workflow["conclusion"] == "cancelled" else "failure"

    phases = [_normalize_phase(row) for row in _list(report.get("phases")) if isinstance(row, Mapping)]
    warnings = [_sanitize_text(item) for item in _list(report.get("warnings"))]
    warnings = [item for item in warnings if item]
    if malformed_artifact:
        warnings.append("Hourly artifact could not be parsed; limited workflow metadata is displayed.")

    report_error = _dict(report.get("error"))
    error = None
    if report_error:
        error = {
            "code": _sanitize_text(report_error.get("code"), limit=80) or "HOURLY_WORKFLOW_ERROR",
            "message": _sanitize_text(report_error.get("message")) or "Hourly workflow reported an error.",
        }
    elif workflow["conclusion"] not in {"success", "neutral", "skipped"} or malformed_artifact:
        error = _fallback_error(str(workflow["conclusion"]), malformed=malformed_artifact)

    runtime_mode = _sanitize_text(_first(runtime_source.get("mode"), report.get("mode"), default="UNKNOWN"), limit=32) or "UNKNOWN"
    broker_mode = _sanitize_text(_first(runtime_source.get("brokerMode"), runtime_source.get("broker_mode"), report.get("broker_mode"), default="UNKNOWN"), limit=32) or "UNKNOWN"
    dry_run = _bool(_first(runtime_source.get("dryRun"), runtime_source.get("dry_run"), default=runtime_mode == "SIMULATOR"))
    runtime = {
        "mode": runtime_mode,
        "brokerMode": broker_mode,
        "dryRun": dry_run,
        "liveTradingEnabled": False,
        "flow": _sanitize_text(_first(runtime_source.get("flow"), report.get("flow"), default="hourly_portfolio_cycle"), limit=64),
    }

    current_success = workflow["conclusion"] == "success" and cycle_status in {"success", "completed"}
    previous_success = _dict(previous_snapshot.get("lastSuccessfulRun"))
    if current_success:
        last_successful = {
            "generatedAt": generated_at,
            "runId": workflow["runId"],
            "runNumber": workflow["runNumber"],
            "cycleStatus": "success" if cycle_status == "completed" else cycle_status,
        }
    else:
        last_successful = previous_success or None

    age_minutes = max(0.0, (current_time - _utc_datetime(generated_at)).total_seconds() / 60.0)
    snapshot = {
        "schemaVersion": SCHEMA_VERSION,
        "generatedAt": generated_at,
        "workflow": workflow,
        "runtime": runtime,
        "cycle": {
            "id": _sanitize_text(_first(cycle_source.get("id"), request.get("portfolio_cycle_id")), limit=96),
            "status": cycle_status,
            "marketMode": _sanitize_text(_first(cycle_source.get("marketMode"), request.get("market_mode")), limit=64),
            "candidateCount": candidate_count,
            "selectedSymbols": [_sanitize_text(symbol, limit=16) for symbol in selected_symbols if _sanitize_text(symbol, limit=16)],
            "executionAttempted": _bool(_first(cycle_source.get("executionAttempted"), candidate_cycle.get("execute_requested"), execution_status not in {"not_attempted", "skipped", "unknown"})),
            "executionStatus": execution_status,
            "executionReason": execution_reason,
            "partialFillDetected": _bool(_first(cycle_source.get("partialFillDetected"), report.get("partial_fill_detected"), default=False)),
        },
        "phases": phases,
        "account": account,
        "summary": {
            "positionCount": len(positions_source),
            "openOrderCount": len(orders_source),
            "candidateCount": candidate_count,
            "executionStatus": execution_status,
            "executionReason": execution_reason,
        },
        "positions": positions,
        "openOrders": open_orders,
        "signals": signals,
        "warnings": warnings,
        "error": error,
        "lastSuccessfulRun": last_successful,
        "freshness": {
            "expectedIntervalMinutes": expected_interval_minutes,
            "ageMinutes": round(age_minutes, 2),
            "isStale": age_minutes > stale_after_minutes,
            "staleAfterMinutes": stale_after_minutes,
        },
        "privacy": {"mode": privacy_mode, "valuesMasked": privacy_masked},
    }
    if set(snapshot) != TOP_LEVEL_KEYS:
        raise AssertionError("Snapshot top-level allowlist mismatch")
    json.dumps(snapshot, allow_nan=False)
    return snapshot


def _load_json(path: Path | None) -> tuple[dict[str, Any], bool]:
    if path is None or not path.exists():
        return {}, True
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, True
    return (_dict(payload), not isinstance(payload, Mapping))


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a frontend-safe dashboard snapshot JSON.")
    parser.add_argument("--input", type=Path, default=Path("reports/hourly-auto-trading-report.json"))
    parser.add_argument("--workflow-metadata", type=Path)
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--output", type=Path, default=Path("reports/latest-dashboard-snapshot.json"))
    parser.add_argument("--privacy-mode", choices=sorted(PRIVACY_MODES), default=os.getenv("DASHBOARD_SNAPSHOT_PRIVACY_MODE", "masked"))
    parser.add_argument("--expected-interval-minutes", type=int, default=60)
    parser.add_argument("--stale-after-minutes", type=int, default=120)
    args = parser.parse_args()

    report, malformed = _load_json(args.input)
    metadata, _ = _load_json(args.workflow_metadata)
    previous, _ = _load_json(args.previous)
    snapshot = build_snapshot(
        report,
        workflow_metadata=metadata,
        previous_snapshot=previous,
        privacy_mode=args.privacy_mode,
        expected_interval_minutes=args.expected_interval_minutes,
        stale_after_minutes=args.stale_after_minutes,
        malformed_artifact=malformed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Wrote dashboard snapshot: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build a safe report when a completed workflow produced no hourly artifact."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

PAPER_WORKFLOWS = {
    "Hourly Auto Trading",
    "Alpaca Paper Soak",
    "Manual Alpaca Paper Trading",
}
FAILED_CONCLUSIONS = {"failure", "cancelled", "timed_out", "action_required"}
VALID_RUNTIME_MODES = {"PAPER", "SIMULATOR"}
VALID_BROKER_MODES = {"ALPACA", "SIMULATOR"}


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return as_dict(payload)


def workflow_error(conclusion: str) -> dict[str, str] | None:
    if conclusion not in FAILED_CONCLUSIONS:
        return None
    if conclusion == "cancelled":
        return {
            "code": "HOURLY_WORKFLOW_CANCELLED",
            "message": "The Paper workflow was cancelled before a new artifact was published.",
        }
    return {
        "code": "HOURLY_WORKFLOW_FAILED",
        "message": "The Paper workflow ended before a new artifact was published.",
    }


def paper_workflow(metadata: Mapping[str, Any]) -> bool:
    return str(metadata.get("workflowName") or "Hourly Auto Trading") in PAPER_WORKFLOWS


def normalized_runtime(
    previous: Mapping[str, Any], metadata: Mapping[str, Any]
) -> tuple[str, str, bool]:
    runtime = as_dict(previous.get("runtime"))
    raw_mode = str(runtime.get("mode") or "").upper()
    if raw_mode == "ALPACA_PAPER":
        raw_mode = "PAPER"
    is_paper = paper_workflow(metadata) or raw_mode == "PAPER"
    mode = raw_mode if raw_mode in VALID_RUNTIME_MODES else (
        "PAPER" if is_paper else "SIMULATOR"
    )
    raw_broker = str(runtime.get("brokerMode") or "").upper()
    broker = raw_broker if raw_broker in VALID_BROKER_MODES else (
        "ALPACA" if mode == "PAPER" else "SIMULATOR"
    )
    dry_run = bool(runtime.get("dryRun", mode != "PAPER"))
    if mode == "PAPER":
        broker = "ALPACA"
        dry_run = False
    return mode, broker, dry_run


def minimal_report(metadata: Mapping[str, Any]) -> dict[str, Any]:
    conclusion = str(metadata.get("conclusion") or "unknown").lower()
    paper = paper_workflow(metadata)
    generated_at = (
        metadata.get("completedAt")
        or metadata.get("startedAt")
        or datetime.now(timezone.utc).isoformat()
    )
    cycle_status = (
        "cancelled"
        if conclusion == "cancelled"
        else "failure"
        if conclusion in FAILED_CONCLUSIONS
        else "skipped"
        if conclusion == "skipped"
        else "unknown"
    )
    reason = (
        "scheduled_paper_cycle_not_authorized"
        if conclusion == "skipped"
        else "hourly_artifact_unavailable"
    )
    mode = "PAPER" if paper else "SIMULATOR"
    broker = "ALPACA" if paper else "SIMULATOR"
    return {
        "generated_at": generated_at,
        "workflow": as_dict(metadata),
        "runtime": {
            "mode": mode,
            "brokerMode": broker,
            "dryRun": not paper,
            "liveTradingEnabled": False,
            "flow": "hourly_portfolio_cycle",
        },
        "mode": mode,
        "broker_mode": broker,
        "flow": "hourly_portfolio_cycle",
        "request": {
            "portfolio_cycle_id": None,
            "market_mode": None,
            "execute_requested": False,
        },
        "cycle": {
            "id": None,
            "status": cycle_status,
            "marketMode": None,
            "candidateCount": 0,
            "selectedSymbols": [],
            "executionAttempted": False,
            "executionStatus": "not_attempted",
            "executionReason": reason,
            "partialFillDetected": False,
        },
        "phases": [],
        "account": {
            "cash": None,
            "equity": None,
            "buyingPower": None,
            "status": None,
            "lastSyncedAt": generated_at,
        },
        "positions": [],
        "openOrders": [],
        "signals": [],
        "response": {
            "status": "skipped" if conclusion == "skipped" else "unknown",
            "data": {
                "execution": {
                    "status": "not_attempted",
                    "reason": reason,
                },
                "scanner_count": 0,
                "top_10_symbols": [],
                "curator_signals": [],
            },
        },
        "cycle_status": cycle_status,
        "partial_fill_detected": False,
        "warnings": [
            "No new hourly operator artifact was available; workflow metadata is shown."
        ],
        "error": workflow_error(conclusion),
    }


def has_verified_dashboard_data(previous: Mapping[str, Any]) -> bool:
    if previous.get("schemaVersion") != "dashboard-snapshot.v2":
        return False
    runtime = as_dict(previous.get("runtime"))
    raw_mode = str(runtime.get("mode") or "").upper()
    cycle = as_dict(previous.get("cycle"))
    return (
        raw_mode in VALID_RUNTIME_MODES | {"ALPACA_PAPER"}
        and str(cycle.get("status") or "").lower() not in {"", "unknown"}
    ) or bool(
        as_list(previous.get("positions"))
        or as_list(previous.get("openOrders"))
        or as_list(previous.get("signals"))
        or previous.get("lastSuccessfulRun")
    )


def retained_report(
    previous: Mapping[str, Any], metadata: Mapping[str, Any]
) -> dict[str, Any]:
    if not has_verified_dashboard_data(previous):
        return minimal_report(metadata)
    runtime = as_dict(previous.get("runtime"))
    cycle = as_dict(previous.get("cycle"))
    summary = as_dict(previous.get("summary"))
    mode, broker, dry_run = normalized_runtime(previous, metadata)
    warnings = [
        str(item)[:280]
        for item in as_list(previous.get("warnings"))
        if item not in (None, "")
    ]
    warnings.append(
        "No newer verified hourly artifact was available; the last dashboard data is retained."
    )
    conclusion = str(metadata.get("conclusion") or "unknown").lower()
    execution_status = cycle.get("executionStatus") or summary.get("executionStatus")
    execution_reason = cycle.get("executionReason") or summary.get("executionReason")
    return {
        "generated_at": previous.get("generatedAt")
        or datetime.now(timezone.utc).isoformat(),
        "workflow": as_dict(metadata),
        "runtime": {
            "mode": mode,
            "brokerMode": broker,
            "dryRun": dry_run,
            "liveTradingEnabled": False,
            "flow": runtime.get("flow") or "hourly_portfolio_cycle",
        },
        "mode": mode,
        "broker_mode": broker,
        "flow": runtime.get("flow") or "hourly_portfolio_cycle",
        "request": {
            "portfolio_cycle_id": cycle.get("id"),
            "market_mode": cycle.get("marketMode"),
            "execute_requested": bool(cycle.get("executionAttempted")),
        },
        "cycle": cycle,
        "phases": as_list(previous.get("phases")),
        "account": as_dict(previous.get("account")),
        "positions": as_list(previous.get("positions")),
        "openOrders": as_list(previous.get("openOrders")),
        "signals": as_list(previous.get("signals")),
        "response": {
            "status": "retained",
            "data": {
                "execution": {
                    "status": execution_status or "not_attempted",
                    "reason": execution_reason,
                },
                "scanner_count": summary.get("candidateCount")
                or cycle.get("candidateCount")
                or 0,
                "top_10_symbols": as_list(cycle.get("selectedSymbols")),
                "curator_signals": as_list(previous.get("signals")),
            },
        },
        "cycle_status": cycle.get("status") or "unknown",
        "partial_fill_detected": bool(cycle.get("partialFillDetected")),
        "warnings": warnings,
        "error": workflow_error(conclusion),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--workflow-metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report = retained_report(
        load_json(args.previous), load_json(args.workflow_metadata)
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        "Built dashboard fallback report: "
        f"mode={report['runtime']['mode']} cycle_status={report['cycle_status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

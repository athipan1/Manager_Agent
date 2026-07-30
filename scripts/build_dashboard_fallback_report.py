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


def minimal_report(metadata: Mapping[str, Any]) -> dict[str, Any]:
    workflow_name = str(metadata.get("workflowName") or "Hourly Auto Trading")
    conclusion = str(metadata.get("conclusion") or "unknown").lower()
    paper = workflow_name in PAPER_WORKFLOWS
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
    return {
        "generated_at": generated_at,
        "workflow": as_dict(metadata),
        "runtime": {
            "mode": "PAPER" if paper else "SIMULATOR",
            "brokerMode": "ALPACA" if paper else "SIMULATOR",
            "dryRun": not paper,
            "liveTradingEnabled": False,
            "flow": "hourly_portfolio_cycle",
        },
        "mode": "PAPER" if paper else "SIMULATOR",
        "broker_mode": "ALPACA" if paper else "SIMULATOR",
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


def retained_report(
    previous: Mapping[str, Any], metadata: Mapping[str, Any]
) -> dict[str, Any]:
    if previous.get("schemaVersion") != "dashboard-snapshot.v2":
        return minimal_report(metadata)
    runtime = as_dict(previous.get("runtime"))
    cycle = as_dict(previous.get("cycle"))
    summary = as_dict(previous.get("summary"))
    warnings = [
        str(item)[:280] for item in as_list(previous.get("warnings")) if item not in (None, "")
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
            "mode": runtime.get("mode") or "PAPER",
            "brokerMode": runtime.get("brokerMode") or "ALPACA",
            "dryRun": bool(runtime.get("dryRun", False)),
            "liveTradingEnabled": False,
            "flow": runtime.get("flow") or "hourly_portfolio_cycle",
        },
        "mode": runtime.get("mode") or "PAPER",
        "broker_mode": runtime.get("brokerMode") or "ALPACA",
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

    previous = load_json(args.previous)
    metadata = load_json(args.workflow_metadata)
    report = retained_report(previous, metadata)
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

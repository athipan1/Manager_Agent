#!/usr/bin/env python3
"""Build and verify a safe artifact for an intentionally disabled hourly Paper schedule.

This path must stay lightweight: it never contacts agents, databases, Risk,
Execution, Alpaca, or Docker. Its only job is to make an intentional control
state distinguishable from a missing hourly artifact.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "hourly-control-cycle.v1"
REASON_CODE = "hourly_schedule_disabled"
MARKET_MODE = "SCHEDULE_DISABLED"


def _integer(value: str | None) -> int | None:
    try:
        parsed = int(value or "")
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _workflow() -> dict[str, Any]:
    run_id = _integer(os.getenv("GITHUB_RUN_ID"))
    run_number = _integer(os.getenv("GITHUB_RUN_NUMBER"))
    repository = os.getenv("GITHUB_REPOSITORY", "").strip()
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    return {
        "runId": run_id,
        "runNumber": run_number,
        "runUrl": f"{server}/{repository}/actions/runs/{run_id}"
        if repository and run_id
        else None,
        "workflowName": os.getenv("GITHUB_WORKFLOW", "Hourly Auto Trading"),
        "eventName": os.getenv("GITHUB_EVENT_NAME", "schedule"),
        "status": "in_progress",
        "conclusion": "unknown",
    }


def build_control_artifact(*, observed_at: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    observed_at = observed_at or datetime.now(timezone.utc).isoformat()
    workflow = _workflow()
    run_id = workflow.get("runId")
    run_number = workflow.get("runNumber")
    suffix = str(run_id or run_number or int(datetime.now(timezone.utc).timestamp()))
    cycle_id = f"hourly-control-{suffix}"

    phases = [
        {"name": "preflight", "status": "success", "message": REASON_CODE},
        {"name": "portfolio_review", "status": "skipped", "message": REASON_CODE},
        {"name": "protection_reconciliation", "status": "skipped", "message": REASON_CODE},
        {"name": "scanner", "status": "skipped", "message": REASON_CODE},
        {"name": "backtest", "status": "skipped", "message": REASON_CODE},
        {"name": "risk", "status": "not_attempted", "message": REASON_CODE},
        {"name": "execution", "status": "not_attempted", "message": REASON_CODE},
        {"name": "final_reconciliation", "status": "success", "message": REASON_CODE},
    ]

    report = {
        "generated_at": observed_at,
        "workflow": workflow,
        "runtime": {
            "mode": "PAPER",
            "brokerMode": "ALPACA",
            "dryRun": False,
            "liveTradingEnabled": False,
            "flow": "hourly_portfolio_cycle",
        },
        "mode": "PAPER",
        "broker_mode": "ALPACA",
        "flow": "hourly_portfolio_cycle",
        "request": {
            "portfolio_cycle_id": cycle_id,
            "market_mode": MARKET_MODE,
            "execute_requested": False,
        },
        "cycle": {
            "id": cycle_id,
            "status": "controlled_no_trade",
            "marketMode": MARKET_MODE,
            "candidateCount": 0,
            "selectedSymbols": [],
            "executionAttempted": False,
            "executionStatus": "not_attempted",
            "executionReason": REASON_CODE,
            "controlledNoTradeReason": REASON_CODE,
            "brokerOrdersSubmitted": False,
            "partialFillDetected": False,
        },
        "phases": phases,
        "account": {
            "cash": None,
            "equity": None,
            "buyingPower": None,
            "status": None,
            "lastSyncedAt": observed_at,
        },
        "positions": [],
        "openOrders": [],
        "signals": [],
        "response": {
            "status": "controlled_no_trade",
            "data": {
                "execution": {
                    "status": "not_attempted",
                    "reason": REASON_CODE,
                    "brokerOrdersSubmitted": False,
                },
                "scanner_count": 0,
                "top_10_symbols": [],
                "curator_signals": [],
            },
        },
        "partial_fill_detected": False,
        "broker_orders_submitted": False,
        "cycle_status": "controlled_no_trade",
        "warnings": [
            "Hourly Paper schedule is intentionally disabled; no agent or broker mutation was attempted."
        ],
        "error": None,
    }

    marker = {
        "schemaVersion": SCHEMA_VERSION,
        "cycleClass": "control",
        "reasonCode": REASON_CODE,
        "cycleId": cycle_id,
        "correlationId": cycle_id,
        "workflowRunId": run_id,
        "observedAt": observed_at,
        "artifactBacked": True,
    }
    preflight = {
        "status": "controlled_no_trade",
        "generated_at": observed_at,
        "portfolio_cycle_id": cycle_id,
        "correlation_id": cycle_id,
        "market_mode": MARKET_MODE,
        "reason_code": REASON_CODE,
        "control_cycle": True,
        "runtime": {
            "trading_mode": "PAPER",
            "broker_mode": "ALPACA",
            "dry_run": False,
            "paper_automation": False,
        },
    }
    return report, {"marker": marker, "preflight": preflight}


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def verify_control_artifact(reports_dir: Path) -> None:
    report = _load(reports_dir / "hourly-auto-trading-report.json")
    marker = _load(reports_dir / "hourly-control-cycle.json")
    preflight = _load(reports_dir / "hourly-preflight.json")
    cycle = report.get("cycle") or {}
    if cycle.get("status") != "controlled_no_trade":
        raise ValueError("control cycle must be controlled_no_trade")
    if cycle.get("executionReason") != REASON_CODE:
        raise ValueError("control cycle reason is invalid")
    if cycle.get("executionAttempted") is not False:
        raise ValueError("control cycle must not attempt execution")
    if cycle.get("brokerOrdersSubmitted") is not False:
        raise ValueError("control cycle must not submit broker orders")
    if marker.get("schemaVersion") != SCHEMA_VERSION:
        raise ValueError("control marker schema is invalid")
    if marker.get("cycleClass") != "control" or marker.get("artifactBacked") is not True:
        raise ValueError("control marker classification is invalid")
    if preflight.get("control_cycle") is not True:
        raise ValueError("control preflight marker is missing")
    if preflight.get("portfolio_cycle_id") != cycle.get("id"):
        raise ValueError("control artifact cycle IDs do not match")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        verify_control_artifact(args.reports_dir)
        print("Verified hourly control artifact contract")
        return 0

    report, supporting = build_control_artifact()
    _write(args.reports_dir / "hourly-auto-trading-report.json", report)
    _write(args.reports_dir / "hourly-control-cycle.json", supporting["marker"])
    _write(args.reports_dir / "hourly-preflight.json", supporting["preflight"])
    verify_control_artifact(args.reports_dir)
    print(
        "Built hourly control artifact: "
        f"cycle={report['cycle']['id']} reason={REASON_CODE}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

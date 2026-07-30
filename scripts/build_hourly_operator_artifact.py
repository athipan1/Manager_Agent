#!/usr/bin/env python3
"""Build a sanitized hourly operator report even when the trading cycle fails early."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _load_json(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.exists():
        return {}, f"Missing phase report: {path.name}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, f"Invalid phase report: {path.name}"
    if not isinstance(payload, dict):
        return {}, f"Invalid phase report object: {path.name}"
    return payload, None


def _response_data(response: Mapping[str, Any]) -> dict[str, Any]:
    data = _dict(response.get("data"))
    nested = _dict(data.get("data"))
    return nested or data


def _runtime_mode(preflight: Mapping[str, Any]) -> tuple[str, str, bool]:
    runtime = _dict(preflight.get("runtime"))
    broker_mode = str(runtime.get("broker_mode") or os.getenv("BROKER_MODE") or "SIMULATOR").strip().upper()
    paper_automation = bool(runtime.get("paper_automation"))
    dry_run = bool(runtime.get("dry_run", str(os.getenv("DRY_RUN", "true")).lower() == "true"))
    if paper_automation and broker_mode == "ALPACA" and not dry_run:
        return "ALPACA_PAPER", "ALPACA", False
    return "SIMULATOR", "SIMULATOR" if broker_mode != "ALPACA" else broker_mode, True


def _step_status(value: Any, *, default: str = "unknown") -> str:
    status = str(value or default).strip().lower()
    mapping = {
        "success": "success",
        "failure": "failure",
        "cancelled": "cancelled",
        "skipped": "skipped",
        "neutral": "warning",
        "in_progress": "running",
        "queued": "pending",
        "": default,
    }
    allowed = {"pending", "running", "success", "warning", "skipped", "not_attempted", "failure", "cancelled", "unknown"}
    return mapping.get(status, status if status in allowed else "unknown")


def _phase(name: str, status: Any, message: Any = None) -> dict[str, Any]:
    clean_message = None if message in (None, "") else " ".join(str(message).split())[:280]
    return {"name": name, "status": _step_status(status), "message": clean_message}


def _safe_symbols(rows: Any) -> list[str]:
    result: list[str] = []
    for row in _list(rows):
        symbol = row.get("symbol") if isinstance(row, Mapping) else row
        symbol = str(symbol or "").strip().upper()
        if symbol and symbol not in result:
            result.append(symbol[:16])
    return result


def _safe_account(review: Mapping[str, Any]) -> dict[str, Any]:
    broker = _dict(review.get("broker_snapshot"))
    portfolio = _dict(broker.get("portfolio"))
    account = _dict(broker.get("account")) or _dict(portfolio.get("account")) or _dict(review.get("account"))
    data = _dict(account.get("data")) or account
    return {
        "cash": data.get("cash") or data.get("cash_balance"),
        "equity": data.get("equity") or data.get("portfolio_value"),
        "buyingPower": data.get("buying_power") or data.get("buyingPower"),
        "status": data.get("status"),
        "lastSyncedAt": review.get("generated_at"),
    }


def _safe_positions(review: Mapping[str, Any]) -> list[dict[str, Any]]:
    broker = _dict(review.get("broker_snapshot"))
    positions = broker.get("positions") or review.get("positions") or []
    positions = _dict(positions).get("data") if isinstance(positions, Mapping) else positions
    safe: list[dict[str, Any]] = []
    for row in _list(positions):
        if not isinstance(row, Mapping):
            continue
        safe.append({
            "symbol": str(row.get("symbol") or "UNKNOWN")[:16],
            "quantity": row.get("quantity") or row.get("qty"),
            "averageCost": row.get("averageCost") or row.get("average_cost") or row.get("avg_entry_price"),
            "currentPrice": row.get("currentPrice") or row.get("current_price") or row.get("current_market_price"),
            "marketValue": row.get("marketValue") or row.get("market_value"),
            "unrealizedPnL": row.get("unrealizedPnL") or row.get("unrealized_pl"),
            "bucket": row.get("bucket") or row.get("strategy_bucket") or "unassigned",
        })
    return safe


def _safe_orders(review: Mapping[str, Any]) -> list[dict[str, Any]]:
    broker = _dict(review.get("broker_snapshot"))
    orders = broker.get("orders") or review.get("open_orders") or []
    orders = _dict(orders).get("data") if isinstance(orders, Mapping) else orders
    safe: list[dict[str, Any]] = []
    for row in _list(orders):
        if not isinstance(row, Mapping):
            continue
        safe.append({
            "symbol": str(row.get("symbol") or "UNKNOWN")[:16],
            "side": row.get("side"),
            "quantity": row.get("quantity") or row.get("qty"),
            "orderClass": row.get("orderClass") or row.get("order_class"),
            "type": row.get("type") or row.get("order_type"),
            "status": row.get("status") or row.get("broker_status"),
            "takeProfit": row.get("takeProfit") or row.get("take_profit") or row.get("limit_price"),
            "stopLoss": bool(row.get("stopLoss") or row.get("stop_loss") or row.get("stop_price")),
        })
    return safe


def build_hourly_operator_artifact(
    *,
    preflight: Mapping[str, Any] | None,
    cycle: Mapping[str, Any] | None,
    discovery: Mapping[str, Any] | None = None,
    phase_outcomes: Mapping[str, Any] | None = None,
    workflow: Mapping[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    preflight = _dict(preflight)
    cycle = _dict(cycle)
    discovery = _dict(discovery)
    phase_outcomes = _dict(phase_outcomes)
    review = _dict(cycle.get("review"))
    candidate_cycle = _dict(cycle.get("candidate_cycle"))
    manager_response = _dict(candidate_cycle.get("manager_response"))
    manager_data = _response_data(manager_response)
    discovery_data = _response_data(_dict(discovery.get("response")))
    execution = _dict(manager_data.get("execution"))
    ranked = manager_data.get("ranked_candidates") or discovery_data.get("ranked_candidates") or []
    selected_symbols = _safe_symbols(manager_data.get("selected_positions") or discovery_data.get("selected_positions") or ranked)
    candidate_count = int(manager_data.get("scanner_count") or discovery_data.get("scanner_count") or len(ranked) or len(selected_symbols))
    mode, broker_mode, dry_run = _runtime_mode(preflight)
    generated_at = cycle.get("completed_at") or review.get("generated_at") or preflight.get("generated_at") or datetime.now(timezone.utc).isoformat()
    cycle_status = str(cycle.get("status") or ("failure" if phase_outcomes.get("workflow") == "failure" else "unknown")).lower()
    execution_status = str(execution.get("status") or ("not_attempted" if not selected_symbols else "unknown"))
    execution_reason = execution.get("reason") or ("no_preselected_backtest_symbols" if not selected_symbols else None)

    backtest_status = phase_outcomes.get("backtest")
    risk_status = phase_outcomes.get("risk")
    execution_phase_status = phase_outcomes.get("execution")
    if not selected_symbols:
        backtest_status = "skipped"
        risk_status = "skipped"
        execution_phase_status = "not_attempted"
    elif execution_status in {"rejected", "risk_rejected"}:
        risk_status = "failure"
        execution_phase_status = "not_attempted"
    elif execution_status in {"submitted", "executed", "success", "filled", "partial_fill"}:
        risk_status = risk_status or "success"
        execution_phase_status = "success" if execution_status != "partial_fill" else "warning"
    elif execution_status in {"failed", "failure"}:
        execution_phase_status = "failure"

    phases = [
        _phase("preflight", phase_outcomes.get("preflight")),
        _phase("portfolio_review", phase_outcomes.get("portfolio_review")),
        _phase("protection_reconciliation", phase_outcomes.get("protection_reconciliation")),
        _phase("scanner", phase_outcomes.get("scanner"), "No candidate passed the score threshold" if not selected_symbols else None),
        _phase("backtest", backtest_status, "No scanner symbols" if not selected_symbols else None),
        _phase("risk", risk_status, "No candidate" if not selected_symbols else None),
        _phase("execution", execution_phase_status, execution_reason),
        _phase("final_reconciliation", phase_outcomes.get("final_reconciliation")),
    ]

    signals = manager_data.get("curator_signals") if isinstance(manager_data.get("curator_signals"), list) else []
    sanitized_response = {
        "status": manager_response.get("status") or "unknown",
        "data": {
            "execution": {"status": execution_status, "reason": execution_reason},
            "scanner_count": candidate_count,
            "top_10_symbols": selected_symbols[:10],
            "curator_signals": signals,
        },
    }
    return {
        "generated_at": generated_at,
        "workflow": _dict(workflow),
        "runtime": {
            "mode": mode,
            "brokerMode": broker_mode,
            "dryRun": dry_run,
            "liveTradingEnabled": False,
            "flow": "hourly_portfolio_cycle",
        },
        "mode": mode,
        "broker_mode": broker_mode,
        "flow": "hourly_portfolio_cycle",
        "request": {
            "portfolio_cycle_id": preflight.get("portfolio_cycle_id") or review.get("portfolio_cycle_id"),
            "market_mode": preflight.get("market_mode"),
            "execute_requested": bool(candidate_cycle.get("execute_requested")),
        },
        "cycle": {
            "id": preflight.get("portfolio_cycle_id") or review.get("portfolio_cycle_id"),
            "status": cycle_status,
            "marketMode": preflight.get("market_mode"),
            "candidateCount": candidate_count,
            "selectedSymbols": selected_symbols,
            "executionAttempted": bool(candidate_cycle.get("execute_requested")),
            "executionStatus": execution_status,
            "executionReason": execution_reason,
            "partialFillDetected": bool(cycle.get("partial_fill_detected")),
        },
        "phases": phases,
        "account": _safe_account(review),
        "positions": _safe_positions(review),
        "openOrders": _safe_orders(review),
        "signals": signals,
        "response": sanitized_response,
        "partial_fill_detected": bool(cycle.get("partial_fill_detected")),
        "cycle_status": cycle_status,
        "warnings": [str(item)[:280] for item in (warnings or [])],
        "error": None if cycle_status not in {"failure", "cancelled"} else {
            "code": "HOURLY_CYCLE_FAILED" if cycle_status == "failure" else "HOURLY_CYCLE_CANCELLED",
            "message": "Hourly cycle did not complete successfully.",
        },
    }


def _workflow_from_env() -> dict[str, Any]:
    server = os.getenv("GITHUB_SERVER_URL", "https://github.com")
    repository = os.getenv("GITHUB_REPOSITORY", "")
    run_id = os.getenv("GITHUB_RUN_ID", "")
    return {
        "runId": int(run_id) if run_id.isdigit() else None,
        "runNumber": int(os.getenv("GITHUB_RUN_NUMBER", "0") or 0) or None,
        "runUrl": f"{server}/{repository}/actions/runs/{run_id}" if repository and run_id else None,
        "eventName": os.getenv("GITHUB_EVENT_NAME", "unknown"),
        "status": "in_progress",
        "conclusion": "unknown",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight", type=Path, default=Path("reports/hourly-preflight.json"))
    parser.add_argument("--cycle", type=Path, default=Path("reports/hourly-portfolio-cycle.json"))
    parser.add_argument("--discovery", type=Path, default=Path("reports/hourly-pre-backtest-discovery.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/hourly-auto-trading-report.json"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    preflight, preflight_warning = _load_json(args.preflight)

def main() -> int:
    args = parse_args()
    preflight, preflight_warning = _load_json(args.preflight)
    cycle, cycle_warning = _load_json(args.cycle)
    discovery, discovery_warning = _load_json(args.discovery)
    phase_outcomes = {
        "preflight": os.getenv("PHASE_PREFLIGHT_STATUS", "unknown"),
        "portfolio_review": os.getenv("PHASE_PORTFOLIO_REVIEW_STATUS", "unknown"),
        "protection_reconciliation": os.getenv("PHASE_PROTECTION_STATUS", "unknown"),
        "scanner": os.getenv("PHASE_SCANNER_STATUS", "unknown"),
        "backtest": os.getenv("PHASE_BACKTEST_STATUS", "unknown"),
        "risk": os.getenv("PHASE_RISK_STATUS", "unknown"),
        "execution": os.getenv("PHASE_EXECUTION_STATUS", "unknown"),
        "final_reconciliation": os.getenv("PHASE_FINAL_STATUS", "unknown"),
        "workflow": os.getenv("WORKFLOW_OUTCOME", "unknown"),
    }
    warnings = [item for item in (preflight_warning, cycle_warning, discovery_warning) if item]
    artifact = build_hourly_operator_artifact(
        preflight=preflight,
        cycle=cycle,
        discovery=discovery,
        phase_outcomes=phase_outcomes,
        workflow=_workflow_from_env(),
        warnings=warnings,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Built hourly operator artifact: mode={artifact['mode']}, broker_mode={artifact['broker_mode']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

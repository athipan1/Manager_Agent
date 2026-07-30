#!/usr/bin/env python3
"""Build a sanitized hourly operator report from complete or partial phase outputs."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.capture_hourly_dashboard_state import (  # noqa: E402
    RuntimeSafetyError,
    capture_dashboard_state,
)

PHASE_ENV = {
    "preflight": "PHASE_PREFLIGHT_STATUS",
    "portfolio_review": "PHASE_PORTFOLIO_REVIEW_STATUS",
    "protection_reconciliation": "PHASE_PROTECTION_STATUS",
    "scanner": "PHASE_SCANNER_STATUS",
    "backtest": "PHASE_BACKTEST_STATUS",
    "risk": "PHASE_RISK_STATUS",
    "execution": "PHASE_EXECUTION_STATUS",
    "final_reconciliation": "PHASE_FINAL_STATUS",
    "workflow": "WORKFLOW_OUTCOME",
}
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


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def bool_value(value: Any, default: bool = False) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def int_value(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def load_json(path: Path) -> tuple[dict[str, Any], str | None]:
    if not path.exists():
        return {}, f"Missing phase report: {path.name}"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, f"Invalid phase report: {path.name}"
    if not isinstance(payload, dict):
        return {}, f"Invalid phase report object: {path.name}"
    return payload, None


def response_data(response: Mapping[str, Any]) -> dict[str, Any]:
    data = as_dict(response.get("data"))
    return as_dict(data.get("data")) or data


def runtime_mode(
    preflight: Mapping[str, Any], dashboard_state: Mapping[str, Any]
) -> tuple[str, str, bool]:
    runtime = as_dict(preflight.get("runtime"))
    state_runtime = as_dict(dashboard_state.get("runtime"))
    broker = str(
        runtime.get("broker_mode")
        or state_runtime.get("brokerMode")
        or state_runtime.get("broker_mode")
        or os.getenv("BROKER_MODE")
        or "SIMULATOR"
    ).upper()
    dry_run = bool_value(
        runtime.get("dry_run"),
        bool_value(
            state_runtime.get("dryRun"),
            os.getenv("DRY_RUN", "true").lower() != "false",
        ),
    )
    trading_mode = str(
        runtime.get("trading_mode")
        or state_runtime.get("mode")
        or os.getenv("TRADING_MODE")
        or "PAPER"
    ).upper()
    paper_automation = bool_value(runtime.get("paper_automation")) or (
        trading_mode in {"PAPER", "ALPACA_PAPER"}
        and broker == "ALPACA"
        and not dry_run
    )
    if paper_automation:
        return "PAPER", "ALPACA", False
    return "SIMULATOR", broker if broker in {"ALPACA", "SIMULATOR"} else "SIMULATOR", True


def phase_status(value: Any, default: str = "unknown") -> str:
    status = str(value or default).lower()
    status = {
        "neutral": "warning",
        "in_progress": "running",
        "queued": "pending",
        "timed_out": "failure",
        "action_required": "failure",
    }.get(status, status)
    return status if status in PHASE_STATUSES else "unknown"


def phase(name: str, status: Any, message: Any = None) -> dict[str, Any]:
    return {
        "name": name,
        "status": phase_status(status),
        "message": None
        if message in (None, "")
        else " ".join(str(message).split())[:280],
    }


def selected_symbols(rows: Any) -> list[str]:
    result: list[str] = []
    for row in as_list(rows):
        value = row.get("symbol") if isinstance(row, Mapping) else row
        symbol = str(value or "").strip().upper()[:16]
        if symbol and symbol not in result:
            result.append(symbol)
    return result


def safe_account(
    source: Mapping[str, Any], review: Mapping[str, Any], preflight: Mapping[str, Any]
) -> dict[str, Any]:
    account = as_dict(source.get("account")) or as_dict(review.get("account"))
    account = as_dict(account.get("data")) or account
    alpaca = as_dict(preflight.get("alpaca_paper"))
    return {
        "cash": account.get("cash") or account.get("cash_balance"),
        "equity": account.get("equity") or account.get("portfolio_value"),
        "buyingPower": account.get("buying_power") or account.get("buyingPower"),
        "status": account.get("status") or alpaca.get("account_status"),
        "lastSyncedAt": source.get("generated_at")
        or review.get("generated_at")
        or preflight.get("generated_at"),
    }


def safe_positions(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in as_list(source.get("positions")):
        if not isinstance(row, Mapping):
            continue
        protection = as_dict(row.get("protection"))
        result.append(
            {
                "symbol": str(row.get("symbol") or "UNKNOWN")[:16],
                "quantity": row.get("quantity") or row.get("qty"),
                "averageCost": row.get("averageCost")
                or row.get("average_cost")
                or row.get("avg_entry_price"),
                "currentPrice": row.get("currentPrice")
                or row.get("current_price")
                or row.get("current_market_price"),
                "marketValue": row.get("marketValue") or row.get("market_value"),
                "unrealizedPnL": row.get("unrealizedPnL")
                or row.get("unrealized_pl"),
                "bucket": row.get("bucket")
                or row.get("strategy_bucket")
                or "unassigned",
                "protection": {
                    "status": protection.get("status")
                    or row.get("protection_status")
                    or "unknown",
                    "hasStopLoss": bool_value(
                        protection.get("hasStopLoss"),
                        bool_value(row.get("has_protective_stop")),
                    ),
                    "hasTakeProfit": bool_value(
                        protection.get("hasTakeProfit"),
                        bool_value(row.get("has_take_profit")),
                    ),
                    "hasBracket": bool_value(
                        protection.get("hasBracket"),
                        bool_value(row.get("has_bracket")),
                    ),
                },
            }
        )
    return result


def safe_orders(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw = source.get("orders") or source.get("openOrders") or source.get("open_orders")
    result: list[dict[str, Any]] = []
    for row in as_list(raw):
        if not isinstance(row, Mapping):
            continue
        result.append(
            {
                "symbol": str(row.get("symbol") or "UNKNOWN")[:16],
                "side": row.get("side"),
                "quantity": row.get("quantity") or row.get("qty"),
                "orderClass": row.get("orderClass") or row.get("order_class"),
                "type": row.get("type") or row.get("order_type"),
                "status": row.get("status") or row.get("broker_status"),
                "takeProfit": row.get("takeProfit")
                or row.get("take_profit")
                or row.get("limit_price"),
                "stopLoss": bool(
                    row.get("stopLoss")
                    or row.get("stop_loss")
                    or row.get("stop_price")
                ),
            }
        )
    return result


def review_signals(review: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in as_list(review.get("position_decisions")):
        if not isinstance(row, Mapping):
            continue
        action = str(row.get("action") or "HOLD")[:48]
        profit_plan = as_dict(row.get("profit_plan"))
        result.append(
            {
                "symbol": str(row.get("symbol") or "UNKNOWN")[:16],
                "status": action.lower(),
                "skill": "portfolio-review",
                "signal": str(
                    profit_plan.get("primary_action")
                    or profit_plan.get("decision_type")
                    or action
                )[:160],
                "confidence": profit_plan.get("confidence_score"),
            }
        )
    return result


def resolve_cycle_status(
    cycle: Mapping[str, Any], outcomes: Mapping[str, Any]
) -> str:
    explicit = str(cycle.get("status") or "").lower()
    if explicit:
        return "completed" if explicit == "success" else explicit
    workflow = phase_status(outcomes.get("workflow"))
    if workflow in {"failure", "cancelled"}:
        return workflow
    if phase_status(outcomes.get("final_reconciliation")) == "success":
        return "completed"
    if phase_status(outcomes.get("preflight")) == "failure":
        return "failure"
    if any(
        phase_status(outcomes.get(name)) == "success"
        for name in ("portfolio_review", "scanner", "backtest")
    ):
        return "partial"
    return "skipped" if workflow == "skipped" else "unknown"


def build_hourly_operator_artifact(
    *,
    preflight: Mapping[str, Any] | None,
    cycle: Mapping[str, Any] | None,
    discovery: Mapping[str, Any] | None = None,
    review: Mapping[str, Any] | None = None,
    manager: Mapping[str, Any] | None = None,
    dashboard_state: Mapping[str, Any] | None = None,
    phase_outcomes: Mapping[str, Any] | None = None,
    workflow: Mapping[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    preflight = as_dict(preflight)
    cycle = as_dict(cycle)
    discovery = as_dict(discovery)
    outcomes = as_dict(phase_outcomes)
    review = as_dict(cycle.get("review")) or as_dict(review)
    candidate = as_dict(cycle.get("candidate_cycle")) or as_dict(manager)
    dashboard_state = as_dict(dashboard_state)
    source = dashboard_state or as_dict(review.get("broker_snapshot"))
    manager_response = as_dict(candidate.get("manager_response"))
    manager_data = response_data(manager_response)
    discovery_data = response_data(as_dict(discovery.get("response")))
    execution = as_dict(manager_data.get("execution"))
    ranked = manager_data.get("ranked_candidates") or discovery_data.get(
        "ranked_candidates"
    ) or []
    selected = selected_symbols(
        manager_data.get("selected_positions")
        or discovery_data.get("selected_positions")
        or ranked
    )
    candidate_count = int_value(
        manager_data.get("scanner_count")
        or discovery_data.get("scanner_count")
        or len(ranked)
        or len(selected)
    )
    mode, broker, dry_run = runtime_mode(preflight, dashboard_state)
    generated_at = (
        cycle.get("completed_at")
        or dashboard_state.get("generated_at")
        or candidate.get("generated_at")
        or review.get("generated_at")
        or preflight.get("generated_at")
        or datetime.now(timezone.utc).isoformat()
    )
    status = resolve_cycle_status(cycle, outcomes)
    execution_status = str(
        execution.get("status") or ("not_attempted" if not selected else "unknown")
    )
    execution_reason = execution.get("reason") or (
        "no_preselected_backtest_symbols" if not selected else None
    )
    backtest = outcomes.get("backtest")
    risk = outcomes.get("risk")
    execution_phase = outcomes.get("execution")
    if not selected:
        backtest, risk, execution_phase = "skipped", "skipped", "not_attempted"
    elif execution_status in {"rejected", "risk_rejected"}:
        risk, execution_phase = "failure", "not_attempted"
    elif execution_status in {"submitted", "executed", "success", "filled"}:
        risk, execution_phase = risk or "success", "success"
    elif execution_status == "partial_fill":
        risk, execution_phase = risk or "success", "warning"
    elif execution_status in {"failed", "failure"}:
        execution_phase = "failure"
    phases = [
        phase("preflight", outcomes.get("preflight")),
        phase("portfolio_review", outcomes.get("portfolio_review")),
        phase("protection_reconciliation", outcomes.get("protection_reconciliation")),
        phase(
            "scanner",
            outcomes.get("scanner"),
            "No candidate passed the score threshold" if not selected else None,
        ),
        phase("backtest", backtest, "No scanner symbols" if not selected else None),
        phase("risk", risk, "No candidate" if not selected else None),
        phase("execution", execution_phase, execution_reason),
        phase("final_reconciliation", outcomes.get("final_reconciliation")),
    ]
    manager_signals = (
        manager_data.get("curator_signals")
        if isinstance(manager_data.get("curator_signals"), list)
        else []
    )
    signals = [*manager_signals, *review_signals(review)]
    report_warnings = [str(item)[:280] for item in (warnings or [])]
    if not source:
        report_warnings.append(
            "Frontend-safe broker snapshot was unavailable; portfolio rows may be incomplete."
        )
    cycle_id = preflight.get("portfolio_cycle_id") or review.get(
        "portfolio_cycle_id"
    )
    market_mode = (
        preflight.get("market_mode")
        or candidate.get("market_mode")
        or review.get("market_mode")
    )
    execution_attempted = bool_value(candidate.get("execute_requested"))
    partial_fill = bool_value(cycle.get("partial_fill_detected"))
    return {
        "generated_at": generated_at,
        "workflow": as_dict(workflow),
        "runtime": {
            "mode": mode,
            "brokerMode": broker,
            "dryRun": dry_run,
            "liveTradingEnabled": False,
            "flow": "hourly_portfolio_cycle",
        },
        "mode": mode,
        "broker_mode": broker,
        "flow": "hourly_portfolio_cycle",
        "request": {
            "portfolio_cycle_id": cycle_id,
            "market_mode": market_mode,
            "execute_requested": execution_attempted,
        },
        "cycle": {
            "id": cycle_id,
            "status": status,
            "marketMode": market_mode,
            "candidateCount": candidate_count,
            "selectedSymbols": selected,
            "executionAttempted": execution_attempted,
            "executionStatus": execution_status,
            "executionReason": execution_reason,
            "partialFillDetected": partial_fill,
        },
        "phases": phases,
        "account": safe_account(source, review, preflight),
        "positions": safe_positions(source),
        "openOrders": safe_orders(source),
        "signals": signals,
        "response": {
            "status": manager_response.get("status") or "unknown",
            "data": {
                "execution": {
                    "status": execution_status,
                    "reason": execution_reason,
                },
                "scanner_count": candidate_count,
                "top_10_symbols": selected[:10],
                "curator_signals": signals,
            },
        },
        "partial_fill_detected": partial_fill,
        "cycle_status": status,
        "warnings": report_warnings,
        "error": None
        if status not in {"failure", "cancelled"}
        else {
            "code": "HOURLY_CYCLE_FAILED"
            if status == "failure"
            else "HOURLY_CYCLE_CANCELLED",
            "message": "Hourly cycle did not complete successfully.",
        },
    }


def workflow_from_env() -> dict[str, Any]:
    run_id = os.getenv("GITHUB_RUN_ID", "")
    repository = os.getenv("GITHUB_REPOSITORY", "")
    return {
        "runId": int(run_id) if run_id.isdigit() else None,
        "runNumber": int(os.getenv("GITHUB_RUN_NUMBER", "0") or 0) or None,
        "runUrl": (
            f"{os.getenv('GITHUB_SERVER_URL', 'https://github.com')}/"
            f"{repository}/actions/runs/{run_id}"
            if repository and run_id
            else None
        ),
        "eventName": os.getenv("GITHUB_EVENT_NAME", "unknown"),
        "workflowName": os.getenv("GITHUB_WORKFLOW", "Hourly Auto Trading"),
        "status": "in_progress",
        "conclusion": "unknown",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--preflight", type=Path, default=Path("reports/hourly-preflight.json")
    )
    parser.add_argument(
        "--cycle", type=Path, default=Path("reports/hourly-portfolio-cycle.json")
    )
    parser.add_argument(
        "--discovery",
        type=Path,
        default=Path("reports/hourly-pre-backtest-discovery.json"),
    )
    parser.add_argument(
        "--review", type=Path, default=Path("reports/hourly-position-review.json")
    )
    parser.add_argument(
        "--manager", type=Path, default=Path("reports/hourly-manager-cycle.json")
    )
    parser.add_argument(
        "--dashboard-state",
        type=Path,
        default=Path("reports/hourly-dashboard-state.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/hourly-auto-trading-report.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    preflight, preflight_warning = load_json(args.preflight)
    cycle, cycle_warning = load_json(args.cycle)
    discovery, discovery_warning = load_json(args.discovery)
    review, review_warning = load_json(args.review)
    manager, manager_warning = load_json(args.manager)
    dashboard_state, state_warning = load_json(args.dashboard_state)
    if not dashboard_state and preflight.get("status") == "ready":
        try:
            dashboard_state = capture_dashboard_state(
                preflight=preflight, output_path=args.dashboard_state
            )
            state_warning = None
        except RuntimeSafetyError as exc:
            state_warning = (
                "Dashboard state capture unavailable: " f"{type(exc).__name__}"
            )
    outcomes = {
        key: os.getenv(env_name, "unknown") for key, env_name in PHASE_ENV.items()
    }
    artifact = build_hourly_operator_artifact(
        preflight=preflight,
        cycle=cycle,
        discovery=discovery,
        review=review,
        manager=manager,
        dashboard_state=dashboard_state,
        phase_outcomes=outcomes,
        workflow=workflow_from_env(),
        warnings=[
            item
            for item in (
                preflight_warning,
                cycle_warning,
                discovery_warning,
                review_warning,
                manager_warning,
                state_warning,
            )
            if item
        ],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        "Built hourly operator artifact: "
        f"mode={artifact['mode']}, broker_mode={artifact['broker_mode']}, "
        f"cycle_status={artifact['cycle_status']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

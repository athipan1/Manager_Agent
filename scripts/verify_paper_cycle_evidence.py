#!/usr/bin/env python3
"""Verify one Alpaca Paper cycle artifact for soak-test evidence."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


SAFE_SYNC_STATUSES = {"synced", "in_sync", "ok", "matched"}
FAILED_ORDER_STATUSES = {"failed", "rejected", "error", "canceled", "cancelled"}
SAFE_PROTECTION_STATUSES = {"bracket_protected", "tp_sl_protected"}
CONTROLLED_NO_TRADE_REASONS = {
    "market_closed",
    "no_eligible_strategy",
    "no_preselected_backtest_symbols",
}


class EvidenceError(RuntimeError):
    """Raised when evidence files are missing or structurally invalid."""


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def as_list(value: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in (value or []) if isinstance(row, Mapping)]


def unwrap(value: Any) -> Any:
    if isinstance(value, Mapping) and "data" in value:
        return value.get("data")
    return value


def find_one(root: Path, filename: str) -> Path:
    matches = sorted(path for path in root.rglob(filename) if path.is_file())
    if len(matches) != 1:
        raise EvidenceError(
            f"Expected exactly one {filename} artifact; found {len(matches)}."
        )
    return matches[0]


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"{path.name} is missing or invalid.") from exc
    if not isinstance(payload, dict):
        raise EvidenceError(f"{path.name} must contain a JSON object.")
    return payload


def reconciliation_is_safe(value: Any) -> bool:
    data = as_dict(unwrap(value))
    push = as_dict(data.get("database_sync"))
    mismatch = as_dict(data.get("mismatch"))
    summary = as_dict(mismatch.get("summary"))
    status = str(summary.get("status") or data.get("status") or "").lower()
    return (
        data.get("ok") is True and push.get("status") == "success"
    ) or status in SAFE_SYNC_STATUSES


def protection_gaps(value: Any) -> list[str]:
    diagnostics = as_dict(unwrap(value))
    gaps: list[str] = []
    for row in as_list(diagnostics.get("positions")):
        status = str(row.get("protection_status") or "").lower()
        try:
            unprotected = float(row.get("unprotected_quantity") or 0)
        except (TypeError, ValueError):
            unprotected = 1
        if (
            status not in SAFE_PROTECTION_STATUSES
            or unprotected > 0
            or bool(row.get("duplicate_protection"))
            or bool(row.get("quantity_mismatch"))
        ):
            gaps.append(str(row.get("symbol") or "unknown"))
    return gaps


def cycle_completed_safely(
    cycle: Mapping[str, Any], operator: Mapping[str, Any]
) -> bool:
    if str(cycle.get("status") or "").lower() != "completed":
        return False

    operator_status = str(operator.get("cycle_status") or "").lower()
    if operator_status == "completed":
        return True
    if operator_status != "controlled_no_trade":
        return False

    candidate = as_dict(cycle.get("candidate_cycle"))
    manager_response = as_dict(candidate.get("manager_response"))
    manager_data = as_dict(manager_response.get("data"))
    execution = as_dict(manager_data.get("execution"))
    reason = str(candidate.get("reason") or execution.get("reason") or "").lower()
    execution_status = str(execution.get("status") or "").lower()

    return (
        candidate.get("execute_requested") is False
        and execution_status == "not_attempted"
        and reason in CONTROLLED_NO_TRADE_REASONS
    )


def add_check(
    checks: list[dict[str, Any]],
    name: str,
    passed: bool,
    detail: str,
) -> None:
    checks.append({"name": name, "passed": bool(passed), "detail": detail})


def verify_artifact(
    *,
    artifact_dir: Path,
    require_emergency_drill: bool,
) -> dict[str, Any]:
    preflight = load_json(find_one(artifact_dir, "hourly-preflight.json"))
    cycle = load_json(find_one(artifact_dir, "hourly-portfolio-cycle.json"))
    operator = load_json(find_one(artifact_dir, "hourly-auto-trading-report.json"))
    checks: list[dict[str, Any]] = []

    runtime = as_dict(preflight.get("runtime"))
    add_check(
        checks,
        "paper_runtime",
        preflight.get("status") == "ready"
        and runtime.get("paper_automation") is True
        and runtime.get("broker_mode") == "ALPACA"
        and runtime.get("dry_run") is False
        and runtime.get("paper_api_url_valid") is True,
        "Preflight must prove ALPACA Paper automation with DRY_RUN=false.",
    )
    alpaca = as_dict(preflight.get("alpaca_paper"))
    add_check(
        checks,
        "alpaca_account",
        bool(alpaca.get("account_ref")) and alpaca.get("account_status") == "ACTIVE",
        "Alpaca Paper account must be active and represented only by a hash reference.",
    )
    add_check(
        checks,
        "cycle_completed",
        cycle_completed_safely(cycle, operator),
        (
            "The Manager cycle must complete; the operator artifact may report "
            "completed or a validated controlled_no_trade terminal state."
        ),
    )
    add_check(
        checks,
        "post_execution_reconciliation",
        reconciliation_is_safe(cycle.get("post_execution_reconciliation")),
        "Execution and Database must prove post-cycle broker parity.",
    )
    gaps = protection_gaps(cycle.get("post_execution_protection"))
    add_check(
        checks,
        "position_protection",
        not gaps,
        (
            "No open position may have missing, duplicate or quantity-mismatched "
            f"protection; gaps={','.join(gaps) if gaps else 'none'}."
        ),
    )
    order_statuses = as_list(cycle.get("submitted_order_statuses"))
    failed_orders = [
        str(row.get("order_id") or "unknown")
        for row in order_statuses
        if str(row.get("status") or "").lower().split(".")[-1]
        in FAILED_ORDER_STATUSES
    ]
    add_check(
        checks,
        "submitted_orders",
        not failed_orders,
        (
            "Submitted Paper orders must not be failed, rejected or cancelled; "
            f"failed={','.join(failed_orders) if failed_orders else 'none'}."
        ),
    )
    add_check(
        checks,
        "profit_lifecycle_disabled",
        runtime.get("profit_decision_execution_enabled") is False
        and runtime.get("profit_auto_exit_all_enabled") is False,
        (
            "Profit decision execution and automatic exit-all must remain disabled "
            "throughout the soak."
        ),
    )

    if require_emergency_drill:
        drill = load_json(find_one(artifact_dir, "emergency-halt-drill.json"))
        drill_checks = as_dict(drill.get("checks"))
        required = {
            "initially_clear",
            "trip_confirmed",
            "policy_halted",
            "readiness_blocked",
            "risk_probe_rejected",
            "clear_confirmed",
            "readiness_restored",
        }
        add_check(
            checks,
            "emergency_halt_drill",
            drill.get("status") == "passed"
            and all(drill_checks.get(name) is True for name in required),
            "Risk halt must reject the probe and restore readiness after an explicit clear.",
        )

    warnings: list[str] = []
    if cycle.get("partial_fill_detected") is True:
        warnings.append("partial_fill_detected")
    failures = [row["name"] for row in checks if not row["passed"]]
    result = "failure" if failures else "warning" if warnings else "success"
    return {
        "schema_version": "alpaca-paper-cycle-evidence.v1",
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "result": result,
        "check_count": len(checks),
        "failed_check_count": len(failures),
        "failed_checks": failures,
        "warning_count": len(warnings),
        "warnings": warnings,
        "submitted_order_count": len(order_statuses),
        "market_mode": preflight.get("market_mode"),
        "portfolio_cycle_id": preflight.get("portfolio_cycle_id"),
        "checks": checks,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--require-emergency-drill", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        evidence = verify_artifact(
            artifact_dir=args.artifact_dir,
            require_emergency_drill=args.require_emergency_drill,
        )
    except EvidenceError as exc:
        print(f"Alpaca Paper evidence verification failed: {exc}", file=sys.stderr)
        return 1
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(
        "Alpaca Paper evidence result: "
        f"{evidence['result']} ({evidence['check_count']} checks, "
        f"{evidence['warning_count']} warnings)"
    )
    return 1 if evidence["result"] == "failure" else 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Build the operator-facing hourly artifact from the multi-phase cycle files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _load_json(path: Path, *, required: bool = True) -> dict[str, Any]:
    if not path.exists():
        if required:
            raise FileNotFoundError(path)
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


def _response_data(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data")
    if isinstance(data, Mapping):
        nested = data.get("data")
        if isinstance(nested, Mapping):
            return dict(nested)
        return dict(data)
    return {}


def _runtime_mode(preflight: dict[str, Any]) -> tuple[str, str]:
    runtime = _dict(preflight.get("runtime"))
    broker_mode = str(runtime.get("broker_mode") or "SIMULATOR").strip().upper()
    paper_automation = bool(runtime.get("paper_automation"))
    if paper_automation and broker_mode == "ALPACA":
        return "ALPACA_PAPER", "ALPACA"
    return "SIMULATOR", broker_mode or "SIMULATOR"


def _merge_discovery_context(
    manager_response: dict[str, Any],
    discovery: dict[str, Any],
) -> dict[str, Any]:
    response = dict(manager_response)
    manager_data = _response_data(response)
    discovery_response = _dict(discovery.get("response"))
    discovery_data = _response_data(discovery_response)

    passthrough_keys = (
        "allocation_plan",
        "bucket_selection",
        "pre_gate_selected_positions",
        "pre_backtest_selected_positions",
        "selected_positions",
        "exposure_gate",
        "backtest_execution_gate",
        "database_sync",
        "database_context",
        "broker_snapshot_capture",
        "ranked_candidates",
        "scanner_metadata",
        "scanner_count",
        "deep_analysis_count",
        "top_10_symbols",
    )
    for key in passthrough_keys:
        if key not in manager_data and key in discovery_data:
            manager_data[key] = discovery_data[key]

    discovery_summary = _dict(discovery_data.get("portfolio_summary"))
    manager_summary = _dict(manager_data.get("portfolio_summary"))
    if discovery_summary or manager_summary:
        manager_data["portfolio_summary"] = {
            **discovery_summary,
            **manager_summary,
        }

    if not response:
        response = {"status": "success"}
    response["data"] = manager_data
    return response


def build_hourly_operator_artifact(
    *,
    preflight: dict[str, Any],
    cycle: dict[str, Any],
    discovery: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize the new multi-phase cycle into the renderer's stable contract."""

    review = _dict(cycle.get("review"))
    candidate_cycle = _dict(cycle.get("candidate_cycle"))
    manager_response = _dict(candidate_cycle.get("manager_response"))
    response = _merge_discovery_context(manager_response, discovery or {})
    mode, broker_mode = _runtime_mode(preflight)

    generated_at = (
        cycle.get("completed_at")
        or review.get("generated_at")
        or preflight.get("generated_at")
    )
    portfolio_cycle_id = (
        preflight.get("portfolio_cycle_id")
        or review.get("portfolio_cycle_id")
    )

    return {
        "generated_at": generated_at,
        "mode": mode,
        "broker_mode": broker_mode,
        "flow": "hourly_portfolio_cycle",
        "request": {
            "portfolio_cycle_id": portfolio_cycle_id,
            "market_mode": preflight.get("market_mode"),
            "execute_requested": bool(candidate_cycle.get("execute_requested")),
        },
        "response": response,
        "protection_diagnostics": review.get("protection_diagnostics") or {},
        "review": review,
        "candidate_cycle": candidate_cycle,
        "post_execution_reconciliation": (
            cycle.get("post_execution_reconciliation") or {}
        ),
        "post_execution_protection": cycle.get("post_execution_protection") or {},
        "submitted_order_statuses": cycle.get("submitted_order_statuses") or [],
        "partial_fill_detected": bool(cycle.get("partial_fill_detected")),
        "cycle_status": cycle.get("status"),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--preflight",
        type=Path,
        default=Path("reports/hourly-preflight.json"),
    )
    parser.add_argument(
        "--cycle",
        type=Path,
        default=Path("reports/hourly-portfolio-cycle.json"),
    )
    parser.add_argument(
        "--discovery",
        type=Path,
        default=Path("reports/hourly-pre-backtest-discovery.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/hourly-auto-trading-report.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    artifact = build_hourly_operator_artifact(
        preflight=_load_json(args.preflight),
        cycle=_load_json(args.cycle),
        discovery=_load_json(args.discovery, required=False),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(
        "Built hourly operator artifact: "
        f"mode={artifact['mode']}, broker_mode={artifact['broker_mode']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

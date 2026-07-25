#!/usr/bin/env python3
"""Record a successful no-op hourly cycle when Scanner selects no symbols."""

from __future__ import annotations

import json
from pathlib import Path


def build_no_candidate_report(preflight: dict) -> dict:
    return {
        "execute_requested": False,
        "market_mode": preflight.get("market_mode"),
        "reason": "no_preselected_backtest_symbols",
        "manager_response": {
            "status": "success",
            "data": {
                "execution": {
                    "status": "not_attempted",
                    "reason": "no_preselected_backtest_symbols",
                },
                "portfolio_summary": {
                    "approved_positions": 0,
                    "execution_status": "not_attempted",
                },
            },
        },
    }


def main() -> int:
    preflight_path = Path("reports/hourly-preflight.json")
    output_path = Path("reports/hourly-manager-cycle.json")
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    if preflight.get("status") != "ready" or not preflight.get("portfolio_cycle_id"):
        raise ValueError(
            "Hourly preflight must be ready before recording a no-candidate cycle"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(build_no_candidate_report(preflight), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(
        "No preselected symbols passed the safety gates; "
        "recorded a successful no-op cycle."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

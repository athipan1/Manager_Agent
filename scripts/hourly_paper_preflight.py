#!/usr/bin/env python3
"""Validate the GitHub hourly runtime before any trading service starts."""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.hourly_runtime_loader import runtime

RuntimeSafetyError = runtime.RuntimeSafetyError
check_alpaca_paper = runtime.check_alpaca_paper
check_railway_database = runtime.check_railway_database
deterministic_portfolio_cycle_id = runtime.deterministic_portfolio_cycle_id
fetch_market_regime_inputs = runtime.fetch_market_regime_inputs
validate_runtime_environment = runtime.validate_runtime_environment


def _github_output(values: dict[str, Any]) -> None:
    output_path = os.getenv("GITHUB_OUTPUT", "").strip()
    if not output_path:
        return
    with Path(output_path).open("a", encoding="utf-8") as handle:
        for key, value in values.items():
            if isinstance(value, bool):
                rendered = str(value).lower()
            elif isinstance(value, (dict, list)):
                rendered = json.dumps(value, separators=(",", ":"))
            else:
                rendered = str(value)
            handle.write(f"{key}={rendered}\n")


def _account_ref(account_id: str) -> str:
    return hashlib.sha256(account_id.encode("utf-8")).hexdigest()[:12]


def build_preflight() -> dict[str, Any]:
    env = os.environ
    runtime = validate_runtime_environment(env)
    correlation_id = (
        env.get("GITHUB_RUN_ID")
        or env.get("GITHUB_RUN_NUMBER")
        or datetime.now(timezone.utc).strftime("local-%Y%m%dT%H%M%S")
    )

    if not runtime["paper_automation"]:
        cycle_id = deterministic_portfolio_cycle_id(
            account_id="simulator",
        )
        return {
            "status": "ready",
            "runtime": runtime,
            "portfolio_cycle_id": cycle_id,
            "correlation_id": cycle_id,
            "account_ref": "simulator",
            "market_open": False,
            "market_mode": "SIMULATOR_DRY_RUN",
            "railway_database": {"required": False},
            "alpaca_paper": {"required": False},
            "market_regime_inputs": {},
        }

    railway = check_railway_database(
        base_url=env["DATABASE_AGENT_URL"],
        api_key=env["DATABASE_AGENT_API_KEY"],
        correlation_id=correlation_id,
    )
    alpaca = check_alpaca_paper(
        api_url=env["ALPACA_API_URL"],
        api_key_id=env["ALPACA_API_KEY_ID"],
        secret_key=env["ALPACA_SECRET_KEY"],
        correlation_id=correlation_id,
    )
    if not alpaca["account_active"]:
        raise RuntimeSafetyError("Alpaca Paper account is not active and unrestricted.")
    cycle_id = deterministic_portfolio_cycle_id(
        account_id=alpaca["account_id"],
    )
    market_inputs = fetch_market_regime_inputs(
        api_key_id=env["ALPACA_API_KEY_ID"],
        secret_key=env["ALPACA_SECRET_KEY"],
        correlation_id=cycle_id,
    )
    return {
        "status": "ready",
        "runtime": runtime,
        "portfolio_cycle_id": cycle_id,
        "correlation_id": cycle_id,
        "account_ref": _account_ref(alpaca["account_id"]),
        "market_open": alpaca["market_open"],
        "market_mode": alpaca["market_mode"],
        "railway_database": railway,
        "alpaca_paper": {
            "account_ref": _account_ref(alpaca["account_id"]),
            "account_status": alpaca["account_status"],
            "market_open": alpaca["market_open"],
            "market_mode": alpaca["market_mode"],
            "clock_timestamp": alpaca["clock_timestamp"],
            "next_open": alpaca["next_open"],
            "next_close": alpaca["next_close"],
        },
        "market_regime_inputs": market_inputs,
    }


def main() -> int:
    report_path = Path(os.getenv("HOURLY_PREFLIGHT_REPORT", "reports/hourly-preflight.json"))
    try:
        report = build_preflight()
    except RuntimeSafetyError as exc:
        print(f"Hourly Paper preflight failed closed: {exc}", file=sys.stderr)
        return 1
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    _github_output(
        {
            "portfolio_cycle_id": report["portfolio_cycle_id"],
            "correlation_id": report["correlation_id"],
            "market_open": report["market_open"],
            "market_mode": report["market_mode"],
            "paper_automation": report["runtime"]["paper_automation"],
        }
    )
    print(
        "Hourly runtime preflight passed: "
        f"mode={report['market_mode']} cycle={report['portfolio_cycle_id']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

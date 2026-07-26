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


def _unwrap(payload: Any) -> Any:
    if isinstance(payload, dict) and "data" in payload:
        return payload.get("data")
    return payload


def _check_railway_database_compatible(
    *, base_url: str, api_key: str, correlation_id: str
) -> dict[str, Any]:
    """Validate both legacy and current Database_Agent readiness contracts.

    `/health` remains authoritative for runtime mode and connectivity. The newer
    `/ready` response intentionally omits duplicated flags such as `dev_mode` and
    `database_agent_api_key_configured`, so their absence must not be interpreted
    as unsafe when `/health` already proves the fail-closed invariants.
    """
    client = runtime.JsonHttpClient(
        base_url=base_url,
        service_name="Railway Database_Agent",
        headers={"X-API-KEY": api_key},
    )
    health = _unwrap(client.request("/health", correlation_id=correlation_id)) or {}
    ready = _unwrap(client.request("/ready", correlation_id=correlation_id)) or {}
    version = _unwrap(client.request("/version", correlation_id=correlation_id)) or {}

    if not isinstance(health, dict) or health.get("database_connection") != "connected":
        raise RuntimeSafetyError(
            "Railway Database_Agent health did not confirm PostgreSQL connectivity."
        )
    if health.get("dev_mode") is not False:
        raise RuntimeSafetyError(
            "Railway Database_Agent must have DATABASE_DEV_MODE=false."
        )
    if str(health.get("trading_mode") or "").strip().upper() != "PAPER":
        raise RuntimeSafetyError(
            "Railway Database_Agent did not report TRADING_MODE=PAPER."
        )
    if health.get("database_emergency_halt") is True:
        raise RuntimeSafetyError("Railway Database_Agent emergency halt is active.")

    if not isinstance(ready, dict) or ready.get("ready") is not True:
        raise RuntimeSafetyError("Railway Database_Agent readiness check failed.")
    if "dev_mode" in ready and ready.get("dev_mode") is not False:
        raise RuntimeSafetyError("Railway Database_Agent readiness reports dev mode.")
    if (
        "database_agent_api_key_configured" in ready
        and ready.get("database_agent_api_key_configured") is not True
    ):
        raise RuntimeSafetyError(
            "Railway Database_Agent does not report an API key configuration."
        )
    if not isinstance(version, dict) or str(version.get("agent_type") or "").strip() != "database":
        raise RuntimeSafetyError("Railway Database_Agent version contract is invalid.")

    return {
        "health": "connected",
        "ready": True,
        "dev_mode": False,
        "trading_mode": "PAPER",
        "version": str(version.get("version") or "").strip(),
        "schema_version": str(version.get("schema_version") or "").strip(),
    }


def _safe_database_diagnostics() -> dict[str, Any]:
    """Fetch non-secret readiness fields after a fail-closed database error."""
    base_url = os.getenv("DATABASE_AGENT_URL", "").strip()
    api_key = os.getenv("DATABASE_AGENT_API_KEY", "").strip()
    if not base_url or not api_key:
        return {"available": False, "reason": "database credentials unavailable"}

    client = runtime.JsonHttpClient(
        base_url=base_url,
        service_name="Railway Database_Agent diagnostics",
        headers={"X-API-KEY": api_key},
        max_attempts=1,
    )
    result: dict[str, Any] = {"available": True}
    correlation_id = os.getenv("GITHUB_RUN_ID", "database-diagnostic")
    for path, name in (("/health", "health"), ("/ready", "ready"), ("/version", "version")):
        try:
            payload = client.request(path, correlation_id=correlation_id)
            data = payload.get("data") if isinstance(payload, dict) and "data" in payload else payload
            if not isinstance(data, dict):
                result[name] = {"response_type": type(data).__name__}
                continue
            allowed = {
                "status",
                "ready",
                "database_connection",
                "dev_mode",
                "trading_mode",
                "database_emergency_halt",
                "database_agent_api_key_configured",
                "database_provider",
                "database_url_configured",
                "database_ssl_mode",
                "database_cutover_guard_enabled",
                "database_expected_provider",
                "database_require_schema_identity",
                "schema_identity_valid",
                "agent_type",
                "version",
                "schema_version",
            }
            result[name] = {key: data.get(key) for key in sorted(allowed) if key in data}
        except Exception as exc:
            result[name] = {"error_type": type(exc).__name__}
    return result


def build_preflight() -> dict[str, Any]:
    env = os.environ
    runtime_report = validate_runtime_environment(env)
    correlation_id = (
        env.get("GITHUB_RUN_ID")
        or env.get("GITHUB_RUN_NUMBER")
        or datetime.now(timezone.utc).strftime("local-%Y%m%dT%H%M%S")
    )

    if not runtime_report["paper_automation"]:
        cycle_id = deterministic_portfolio_cycle_id(account_id="simulator")
        return {
            "status": "ready",
            "runtime": runtime_report,
            "portfolio_cycle_id": cycle_id,
            "correlation_id": cycle_id,
            "account_ref": "simulator",
            "market_open": False,
            "market_mode": "SIMULATOR_DRY_RUN",
            "railway_database": {"required": False},
            "alpaca_paper": {"required": False},
            "market_regime_inputs": {},
        }

    railway = _check_railway_database_compatible(
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
    cycle_id = deterministic_portfolio_cycle_id(account_id=alpaca["account_id"])
    market_inputs = fetch_market_regime_inputs(
        api_key_id=env["ALPACA_API_KEY_ID"],
        secret_key=env["ALPACA_SECRET_KEY"],
        correlation_id=cycle_id,
    )
    return {
        "status": "ready",
        "runtime": runtime_report,
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
        if "Database_Agent" in str(exc) or "DATABASE_AGENT" in str(exc):
            diagnostics = _safe_database_diagnostics()
            print(
                "Safe Railway Database_Agent diagnostics: "
                + json.dumps(diagnostics, ensure_ascii=False, sort_keys=True),
                file=sys.stderr,
            )
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

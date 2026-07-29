#!/usr/bin/env python3
"""Exercise the runtime Risk_Agent halt without touching broker state."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class DrillError(RuntimeError):
    """Raised when the emergency-halt safety contract is not proven."""

    def __init__(
        self,
        message: str,
        *,
        report: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.report = report


def unwrap(value: Any) -> Any:
    if isinstance(value, dict) and "data" in value:
        return value.get("data")
    return value


def request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    admin_token: str = "",
) -> dict[str, Any]:
    body = None
    headers = {
        "Accept": "application/json",
        "X-Correlation-ID": os.getenv(
            "PORTFOLIO_CYCLE_ID",
            os.getenv("GITHUB_RUN_ID", "emergency-halt-drill"),
        ),
    }
    if payload is not None:
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if admin_token:
        headers["X-Admin-Token"] = admin_token
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/{path.lstrip('/')}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read().decode("utf-8")
            value = json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raise DrillError(
            f"Risk_Agent {method} {path} returned HTTP {exc.code}."
        ) from exc
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise DrillError(
            f"Risk_Agent {method} {path} returned an invalid response."
        ) from exc
    if not isinstance(value, dict):
        raise DrillError(f"Risk_Agent {method} {path} response must be an object.")
    return value


def risk_probe_payload() -> dict[str, Any]:
    return {
        "account_id": 1,
        "symbol": "SPY",
        "side": "buy",
        "entry_price": 100,
        "protection_price": 95,
        "requested_quantity": 1,
        "equity": 10000,
        "trading_mode": "PAPER",
    }


def active_from_policy(response: dict[str, Any]) -> bool:
    data = unwrap(response)
    if not isinstance(data, dict) or type(data.get("emergency_halt")) is not bool:
        raise DrillError("Risk_Agent policy omitted the emergency_halt boolean.")
    return bool(data["emergency_halt"])


def run_drill(*, base_url: str, admin_token: str) -> dict[str, Any]:
    if not admin_token.strip():
        raise DrillError("RISK_ADMIN_TOKEN is required for the halt drill.")
    started_at = datetime.now(timezone.utc)
    reason = f"github-paper-drill:{os.getenv('GITHUB_RUN_ID', 'local')}"
    activated = False
    cleanup: dict[str, Any] = {"attempted": False, "cleared": False}
    report: dict[str, Any] = {
        "schema_version": "risk-emergency-halt-drill.v1",
        "status": "running",
        "started_at": started_at.isoformat(),
        "broker_mutation": False,
        "reason_ref": reason,
        "checks": {},
        "cleanup": cleanup,
    }
    failure: DrillError | None = None
    try:
        initial = request_json(base_url, "/risk/policy")
        if active_from_policy(initial):
            raise DrillError(
                "Risk_Agent was already halted; the drill will not clear an operator halt."
            )
        report["checks"]["initially_clear"] = True

        tripped = unwrap(
            request_json(
                base_url,
                "/risk/halt",
                method="POST",
                payload={"reason": reason},
                admin_token=admin_token,
            )
        )
        if not isinstance(tripped, dict) or tripped.get("active") is not True:
            raise DrillError("Risk_Agent did not confirm the emergency halt.")
        activated = True
        report["checks"]["trip_confirmed"] = True

        policy = request_json(base_url, "/risk/policy")
        if not active_from_policy(policy):
            raise DrillError("Risk_Agent policy did not expose the active halt.")
        report["checks"]["policy_halted"] = True

        ready = unwrap(request_json(base_url, "/ready"))
        if not isinstance(ready, dict) or ready.get("ready") is not False:
            raise DrillError("Risk_Agent readiness did not fail closed while halted.")
        report["checks"]["readiness_blocked"] = True

        probe = request_json(
            base_url,
            "/risk/check",
            method="POST",
            payload=risk_probe_payload(),
        )
        probe_data = unwrap(probe)
        violations = (
            probe_data.get("violations")
            if isinstance(probe_data, dict)
            and isinstance(probe_data.get("violations"), list)
            else []
        )
        if (
            probe.get("status") != "rejected"
            or not isinstance(probe_data, dict)
            or probe_data.get("approved") is not False
            or float(probe_data.get("final_quantity") or 0) != 0
            or "emergency_halt_active" not in violations
        ):
            raise DrillError("Risk_Agent did not reject the halted Paper risk probe.")
        report["checks"]["risk_probe_rejected"] = True

        cleared = unwrap(
            request_json(
                base_url,
                "/risk/halt/clear",
                method="POST",
                payload={"reason": f"{reason}:complete", "confirm": True},
                admin_token=admin_token,
            )
        )
        cleanup["attempted"] = True
        if not isinstance(cleared, dict) or cleared.get("active") is not False:
            raise DrillError("Risk_Agent did not confirm the halt clear.")
        activated = False
        cleanup["cleared"] = True

        final_policy = request_json(base_url, "/risk/policy")
        if active_from_policy(final_policy):
            raise DrillError("Risk_Agent remained halted after the drill clear.")
        final_ready = unwrap(request_json(base_url, "/ready"))
        if not isinstance(final_ready, dict) or final_ready.get("ready") is not True:
            raise DrillError("Risk_Agent readiness did not recover after the drill.")
        report["checks"]["clear_confirmed"] = True
        report["checks"]["readiness_restored"] = True
        report["status"] = "passed"
    except DrillError as exc:
        failure = exc
        report["status"] = "failed"
        report["error"] = str(exc)
    finally:
        if activated:
            cleanup["attempted"] = True
            try:
                cleared = unwrap(
                    request_json(
                        base_url,
                        "/risk/halt/clear",
                        method="POST",
                        payload={
                            "reason": f"{reason}:failure-cleanup",
                            "confirm": True,
                        },
                        admin_token=admin_token,
                    )
                )
                cleanup["cleared"] = bool(
                    isinstance(cleared, dict) and cleared.get("active") is False
                )
            except DrillError as exc:
                cleanup["error"] = str(exc)
    report["completed_at"] = datetime.now(timezone.utc).isoformat()
    if cleanup["attempted"] and cleanup["cleared"] is not True:
        failure = DrillError(
            "Risk_Agent halt cleanup could not prove the halt was cleared."
        )
        report["status"] = "failed"
        report["error"] = str(failure)
    if failure is not None:
        raise DrillError(str(failure), report=report) from failure
    return report


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def main() -> int:
    report_path = Path(
        os.getenv(
            "EMERGENCY_HALT_DRILL_REPORT",
            "reports/emergency-halt-drill.json",
        )
    )
    base_url = os.getenv("RISK_AGENT_URL", "http://localhost:8007")
    admin_token = os.getenv("RISK_ADMIN_TOKEN", "")
    try:
        report = run_drill(base_url=base_url, admin_token=admin_token)
    except DrillError as exc:
        report = exc.report or {
            "schema_version": "risk-emergency-halt-drill.v1",
            "status": "failed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "broker_mutation": False,
            "error": str(exc),
        }
        write_report(report_path, report)
        print(f"Risk emergency-halt drill failed closed: {exc}", file=sys.stderr)
        return 1
    write_report(report_path, report)
    print("Risk emergency-halt drill passed and readiness was restored.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

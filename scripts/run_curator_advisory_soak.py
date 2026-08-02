from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


FORBIDDEN_OUTPUT_KEYS = {
    "api_key",
    "broker_order_id",
    "client_order_id",
    "order_id",
    "private_key",
    "risk_approval_id",
    "secret_key",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _auth_headers(*, admin: bool = False) -> dict[str, str]:
    execute_key = os.getenv("CURATOR_AGENT_API_KEY", "").strip()
    admin_key = os.getenv("CURATOR_ADMIN_API_KEY", "").strip()
    key = admin_key if admin else execute_key
    if not key:
        role = "CURATOR_ADMIN_API_KEY" if admin else "CURATOR_AGENT_API_KEY"
        raise RuntimeError(f"{role} is required")
    return {"X-API-KEY": key}


def request_json(
    method: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    admin: bool = False,
    authenticated: bool = True,
    correlation_id: str,
    timeout_seconds: float = 20.0,
) -> dict[str, Any]:
    base_url = os.getenv("CURATOR_AGENT_URL", "http://127.0.0.1:8010").rstrip("/")
    headers = {
        "Accept": "application/json",
        "X-Correlation-ID": correlation_id,
    }
    if authenticated:
        headers.update(_auth_headers(admin=admin))

    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {}
            if not isinstance(parsed, dict):
                raise RuntimeError(f"{method} {path} returned a non-object response")
            return parsed
    except urllib.error.HTTPError as exc:
        details = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {details}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"{method} {path} is unavailable: {exc}") from exc


def validate_readiness(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    data = data if isinstance(data, dict) else {}
    execution = data.get("execution")
    execution = execution if isinstance(execution, dict) else {}
    worker_execution = execution.get("worker_execution")
    worker_execution = worker_execution if isinstance(worker_execution, dict) else {}

    checks = {
        "ready": data.get("ready") is True,
        "remote_worker_mode": execution.get("mode") == "remote_worker",
        "secure_execution_ready": execution.get("secure_execution_ready") is True,
        "fallback_disabled": execution.get("fallback_enabled") is False,
        "worker_container_mode": worker_execution.get("mode") == "container",
        "worker_network_disabled": worker_execution.get("network_access") is False,
        "worker_read_only": worker_execution.get("read_only_filesystem") is True,
        "shared_work_root_configured": (
            worker_execution.get("shared_work_root_configured") is True
        ),
        "shared_work_root_required": (
            worker_execution.get("shared_work_root_required") is True
        ),
        "worker_url_redacted": "worker_url" not in execution,
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise RuntimeError(f"Curator readiness contract failed: {', '.join(failed)}")
    return checks


def _collect_forbidden_keys(value: Any, *, found: set[str] | None = None) -> set[str]:
    result = found if found is not None else set()
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).lower()
            if normalized in FORBIDDEN_OUTPUT_KEYS:
                result.add(normalized)
            _collect_forbidden_keys(item, found=result)
    elif isinstance(value, list):
        for item in value:
            _collect_forbidden_keys(item, found=result)
    return result


def validate_execution(
    payload: dict[str, Any],
    *,
    expected_output: dict[str, Any],
) -> dict[str, Any]:
    data = payload.get("data")
    data = data if isinstance(data, dict) else {}
    sandbox = data.get("sandbox")
    sandbox = sandbox if isinstance(sandbox, dict) else {}
    output = data.get("output")
    output = output if isinstance(output, dict) else {}

    checks = {
        "execution_success": data.get("execution_status") == "success",
        "remote_worker_backend": data.get("execution_backend") == "remote_worker",
        "fallback_not_used": data.get("fallback_used") is False,
        "sandbox_container_mode": sandbox.get("mode") == "container",
        "sandbox_network_disabled": sandbox.get("network_access") is False,
        "sandbox_read_only": sandbox.get("read_only_filesystem") is True,
        "sandbox_broker_disabled": sandbox.get("broker_access") is False,
        "sandbox_order_placement_disabled": sandbox.get("order_placement") is False,
        "shared_work_root_configured": sandbox.get("shared_work_root_configured") is True,
        "shared_work_root_required": sandbox.get("shared_work_root_required") is True,
        "worker_url_redacted": "worker_url" not in data,
        "deterministic_output": output == expected_output,
        "no_forbidden_output_keys": not _collect_forbidden_keys(output),
    }
    failed = sorted(name for name, passed in checks.items() if not passed)
    if failed:
        raise RuntimeError(f"Curator execution contract failed: {', '.join(failed)}")
    return {
        "checks": checks,
        "output": output,
        "output_hash": _canonical_hash(output),
        "elapsed_ms": data.get("elapsed_ms"),
        "database_telemetry": data.get("database_telemetry"),
    }


def run_soak(*, cycles: int, symbol: str, score: float, run_id: str) -> dict[str, Any]:
    correlation_prefix = f"curator-advisory-soak-{run_id}"
    readiness_before = request_json(
        "GET",
        "/ready",
        authenticated=False,
        correlation_id=f"{correlation_prefix}-ready-before",
    )
    readiness_before_checks = validate_readiness(readiness_before)

    skill_name = f"Curator Advisory Soak {run_id}"
    registered = request_json(
        "POST",
        "/skills/register",
        admin=True,
        correlation_id=f"{correlation_prefix}-register",
        payload={
            "name": skill_name,
            "description": (
                "Deterministic advisory-only skill for repeated remote sandbox verification."
            ),
            "tags": ["advisory", "soak-test", "technical"],
            "code": (
                "def advisory_signal(symbol, score):\n"
                "    return {\n"
                "        'signal': 'hold',\n"
                "        'confidence': 0.5,\n"
                "        'reason': 'deterministic advisory soak',\n"
                "        'symbol': symbol,\n"
                "        'score': score,\n"
                "    }\n"
            ),
            "input_schema": {
                "type": "object",
                "required": ["symbol", "score"],
                "properties": {
                    "symbol": {"type": "string"},
                    "score": {"type": "number"},
                },
                "additionalProperties": False,
            },
            "output_schema": {
                "type": "object",
                "required": ["signal", "confidence", "reason", "symbol", "score"],
                "properties": {
                    "signal": {"type": "string"},
                    "confidence": {"type": "number"},
                    "reason": {"type": "string"},
                    "symbol": {"type": "string"},
                    "score": {"type": "number"},
                },
                "additionalProperties": False,
            },
        },
    )
    skill_id = str((registered.get("data") or {}).get("skill_id") or "")
    if not skill_id:
        raise RuntimeError("Curator register response did not include skill_id")

    approved = request_json(
        "POST",
        f"/skills/{skill_id}/approve",
        admin=True,
        correlation_id=f"{correlation_prefix}-approve",
        payload={
            "approved_by": "curator-advisory-soak",
            "reason": "deterministic isolated runtime verification",
        },
    )
    if (approved.get("data") or {}).get("approval_status") != "approved":
        raise RuntimeError("Curator soak skill was not approved")

    normalized_symbol = symbol.strip().upper()
    expected_output = {
        "signal": "hold",
        "confidence": 0.5,
        "reason": "deterministic advisory soak",
        "symbol": normalized_symbol,
        "score": float(score),
    }
    cycle_results: list[dict[str, Any]] = []
    output_hashes: set[str] = set()
    fallback_count = 0

    for cycle in range(1, cycles + 1):
        started = time.perf_counter()
        execution = request_json(
            "POST",
            f"/skills/{skill_id}/execute",
            correlation_id=f"{correlation_prefix}-cycle-{cycle}",
            timeout_seconds=20.0,
            payload={
                "inputs": {
                    "symbol": normalized_symbol,
                    "score": float(score),
                },
                "function_name": "advisory_signal",
                "timeout_seconds": 2.0,
                "account_id": 1,
                "symbol": normalized_symbol,
                "run_id": f"{run_id}-{cycle}",
                "metadata": {
                    "source_flow": "curator_advisory_soak",
                    "cycle": cycle,
                    "advisory_only": True,
                },
            },
        )
        validated = validate_execution(execution, expected_output=expected_output)
        output_hashes.add(validated["output_hash"])
        if (execution.get("data") or {}).get("fallback_used") is True:
            fallback_count += 1
        cycle_results.append(
            {
                "cycle": cycle,
                "wall_elapsed_ms": round((time.perf_counter() - started) * 1000, 3),
                **validated,
            }
        )

    if len(output_hashes) != 1:
        raise RuntimeError(
            f"Advisory output changed across cycles: {sorted(output_hashes)}"
        )
    if fallback_count:
        raise RuntimeError(f"Sandbox fallback was used {fallback_count} time(s)")

    readiness_after = request_json(
        "GET",
        "/ready",
        authenticated=False,
        correlation_id=f"{correlation_prefix}-ready-after",
    )
    readiness_after_checks = validate_readiness(readiness_after)

    wall_latencies = [float(item["wall_elapsed_ms"]) for item in cycle_results]
    return {
        "status": "success",
        "advisory_only": True,
        "run_id": run_id,
        "skill_id": skill_id,
        "skill_name": skill_name,
        "symbol": normalized_symbol,
        "score": float(score),
        "cycles_requested": cycles,
        "cycles_completed": len(cycle_results),
        "fallback_count": fallback_count,
        "unique_output_hashes": sorted(output_hashes),
        "latency_ms": {
            "minimum": min(wall_latencies),
            "maximum": max(wall_latencies),
            "average": round(sum(wall_latencies) / len(wall_latencies), 3),
        },
        "readiness_before": readiness_before_checks,
        "readiness_after": readiness_after_checks,
        "cycles": cycle_results,
        "started_at": cycle_results and cycle_results[0].get("started_at"),
        "completed_at": _utc_now(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run repeated advisory-only Curator sandbox executions."
    )
    parser.add_argument("--cycles", type=int, default=12)
    parser.add_argument("--symbol", default="TEST")
    parser.add_argument("--score", type=float, default=0.5)
    parser.add_argument(
        "--run-id",
        default=os.getenv("GITHUB_RUN_ID") or str(int(time.time())),
    )
    parser.add_argument(
        "--output-json",
        default="reports/curator-advisory-soak.json",
    )
    args = parser.parse_args()
    if not 1 <= args.cycles <= 100:
        parser.error("--cycles must be between 1 and 100")
    if not args.symbol.strip():
        parser.error("--symbol must not be empty")
    if not 0 <= args.score <= 1:
        parser.error("--score must be between 0 and 1")
    return args


def main() -> int:
    args = parse_args()
    output_path = Path(args.output_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    started_at = _utc_now()
    try:
        report = run_soak(
            cycles=args.cycles,
            symbol=args.symbol,
            score=args.score,
            run_id=str(args.run_id),
        )
        report["started_at"] = started_at
        report["completed_at"] = _utc_now()
        exit_code = 0
    except Exception as exc:
        report = {
            "status": "failed",
            "advisory_only": True,
            "run_id": str(args.run_id),
            "cycles_requested": args.cycles,
            "started_at": started_at,
            "completed_at": _utc_now(),
            "error": str(exc),
        }
        exit_code = 1

    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())

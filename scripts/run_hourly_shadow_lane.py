from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


MINIMUM_SHADOW_OBSERVATIONS = 100


def _post_json(url: str, payload: Dict[str, Any], timeout: int = 120) -> Dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"POST {url} returned HTTP {exc.code}: {body}") from exc


def _research_candidates(scanner_report: Dict[str, Any]) -> list[dict]:
    response = scanner_report.get("response") or {}
    data = response.get("data") if isinstance(response, dict) else {}
    if not isinstance(data, dict):
        return []
    rows = data.get("research_candidates") or []
    return [dict(row) for row in rows if isinstance(row, dict)]


def _verify_shadow_safety(result: Dict[str, Any]) -> None:
    required = {
        "execution_mode": "shadow",
        "broker_order_authorized": False,
        "risk_approval_allowed": False,
        "execution_agent_allowed": False,
        "risk_call_count": 0,
        "execution_call_count": 0,
        "broker_order_count": 0,
    }
    failures = [
        f"{key}={result.get(key)!r}, expected {expected!r}"
        for key, expected in required.items()
        if result.get(key) != expected
    ]
    if failures:
        raise RuntimeError("Shadow safety invariant failed: " + "; ".join(failures))


def _verify_performance_floor(performance_response: Dict[str, Any]) -> None:
    data = performance_response.get("data") or {}
    if not isinstance(data, dict):
        raise RuntimeError("Performance shadow response has no data object")
    if data.get("broker_order_authorized") is not False:
        raise RuntimeError("Performance shadow summary unexpectedly authorizes broker orders")
    minimum = int(data.get("minimum_observations_for_paper_review") or 0)
    count = int(data.get("observation_count") or 0)
    if minimum < MINIMUM_SHADOW_OBSERVATIONS:
        raise RuntimeError(
            f"Shadow paper-review floor was weakened: observed minimum={minimum}"
        )
    if count < minimum:
        if data.get("expectancy_eligible_for_promotion") is not False:
            raise RuntimeError("Shadow expectancy became promotion-eligible too early")
        if data.get("promotion_net_expectancy_pct") is not None:
            raise RuntimeError("Promotion expectancy was exposed before sample floor")
        if data.get("paper_review_ready") is not False:
            raise RuntimeError("Paper review became ready before sample floor")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Advance research-only Shadow Trading from Scanner preselection evidence."
    )
    parser.add_argument("--scanner-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--manager-url",
        default=os.getenv("MANAGER_AGENT_URL", "http://localhost:8000"),
    )
    parser.add_argument(
        "--performance-url",
        default=os.getenv("PERFORMANCE_AGENT_URL", "http://localhost:8013"),
    )
    parser.add_argument(
        "--account-id",
        default=os.getenv("SHADOW_ACCOUNT_ID", "1"),
    )
    parser.add_argument(
        "--cycle-id",
        default=os.getenv("PORTFOLIO_CYCLE_ID") or os.getenv("GITHUB_RUN_ID") or "manual-shadow-cycle",
    )
    parser.add_argument(
        "--max-marks",
        type=int,
        default=int(os.getenv("SHADOW_MAX_MARKS", "6")),
    )
    args = parser.parse_args()

    scanner_report = json.loads(args.scanner_report.read_text(encoding="utf-8"))
    candidates = _research_candidates(scanner_report)
    correlation_id = f"shadow-{args.cycle_id}"
    shadow_payload = {
        "account_id": args.account_id,
        "correlation_id": correlation_id,
        "cycle_id": args.cycle_id,
        "candidates": candidates,
        "max_marks": args.max_marks,
        "cost_buffer_bps": float(os.getenv("SHADOW_COST_BUFFER_BPS", "2.0")),
    }

    output: Dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stage": "hourly_shadow_lane",
        "status": "running",
        "cycle_id": args.cycle_id,
        "research_candidate_count": len(candidates),
        "shadow": None,
        "performance": None,
    }

    try:
        shadow = _post_json(
            args.manager_url.rstrip("/") + "/shadow-trading/hourly",
            shadow_payload,
        )
        _verify_shadow_safety(shadow)
        outcomes = shadow.get("closed_outcomes") or []
        performance = _post_json(
            args.performance_url.rstrip("/") + "/performance/shadow",
            {
                "outcomes": outcomes,
                "minimum_observations_for_paper_review": MINIMUM_SHADOW_OBSERVATIONS,
            },
        )
        _verify_performance_floor(performance)
        output.update(
            {
                "status": "success",
                "shadow": shadow,
                "performance": performance,
                "closed_observation_count": len(outcomes),
                "risk_call_count": 0,
                "execution_call_count": 0,
                "broker_order_count": 0,
            }
        )
    except Exception as exc:
        output.update(
            {
                "status": "error",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(output, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"Hourly Shadow lane failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(output, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    print(
        "Hourly Shadow lane complete: "
        f"research_candidates={len(candidates)}, "
        f"actions={shadow.get('action_count', 0)}, "
        f"closed={output['closed_observation_count']}, "
        "risk_calls=0, execution_calls=0, broker_orders=0"
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Live integration smoke test for Portfolio Allocation Mode.

Use this when all services are running (Manager, Scanner, Fundamental,
Technical, Risk, Execution, Database, Learning). It calls Manager's public
/discover-analyze-trade endpoint and validates that the end-to-end response is
portfolio-first, not single-winner-first.

Example:
    MANAGER_AGENT_URL=http://localhost:8000 \
    python scripts/integration_portfolio_smoke.py --dry-run

By default this script sets execute=false for a safe dry run. Pass --execute only
when your environment is paper/simulator mode and you intentionally want Manager
to send approved orders to Execution_Agent.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, List


REQUIRED_DATA_FIELDS = [
    "allocation_plan",
    "bucket_selection",
    "selected_positions",
    "risk_approvals",
    "execution_candidates",
    "portfolio_summary",
    "ranked_candidates",
]


def post_json(url: str, payload: Dict[str, Any], timeout: int) -> Dict[str, Any]:
    request = urllib.request.Request(
        url=url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {url}: {body}") from exc


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def assert_portfolio_contract(body: Dict[str, Any], *, execute: bool) -> None:
    if body.get("status") != "success":
        fail(f"Manager returned non-success status: {body.get('status')} error={body.get('error')}")

    data = body.get("data") or {}
    if data.get("mode") != "portfolio_allocation":
        fail(f"Expected mode=portfolio_allocation, got {data.get('mode')!r}")

    missing = [field for field in REQUIRED_DATA_FIELDS if field not in data]
    if missing:
        fail(f"Missing portfolio fields: {missing}")

    if "winner" in data or "trade_decision" in data:
        fail("Response still exposes top-level winner/trade_decision; expected these only under legacy.")

    plan = data.get("allocation_plan") or {}
    buckets = plan.get("buckets") or {}
    expected_weights = {
        "core_dividend": 0.5,
        "value_rebound": 0.3,
        "news_momentum": 0.2,
    }
    for bucket, expected in expected_weights.items():
        actual = ((buckets.get(bucket) or {}).get("target_weight"))
        if actual != expected:
            fail(f"Bucket {bucket} expected target_weight={expected}, got {actual}")

    selected_positions: List[Dict[str, Any]] = data.get("selected_positions") or []
    if not selected_positions:
        fail("No selected_positions returned. Scanner/analysis may not have produced eligible candidates.")

    for position in selected_positions:
        for field in ("symbol", "strategy_bucket", "target_weight", "allocation_pct"):
            if field not in position:
                fail(f"Selected position missing {field}: {position}")

    summary = data.get("portfolio_summary") or {}
    if summary.get("selected_positions") != len(selected_positions):
        fail("portfolio_summary.selected_positions does not match selected_positions length")

    if execute:
        if not data.get("risk_approvals"):
            fail("execute=true but risk_approvals is empty")
        if (data.get("execution") or {}).get("status") not in {"submitted", "manual_approval_required", "rejected", "failed"}:
            fail(f"Unexpected execution status: {(data.get('execution') or {}).get('status')}")

    print("PASS: Portfolio Allocation Mode contract is valid")
    print(json.dumps({
        "report_id": data.get("report_id"),
        "selected_positions": [p.get("symbol") for p in selected_positions],
        "portfolio_summary": summary,
        "execution_status": (data.get("execution") or {}).get("status"),
    }, indent=2, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Live Manager_Agent portfolio integration smoke test")
    parser.add_argument("--manager-url", default=os.getenv("MANAGER_AGENT_URL", "http://localhost:8000"))
    parser.add_argument("--account-id", default=os.getenv("DEFAULT_ACCOUNT_ID", "1"))
    parser.add_argument("--max-universe", type=int, default=int(os.getenv("INTEGRATION_MAX_UNIVERSE", "20")))
    parser.add_argument("--top-n", type=int, default=int(os.getenv("INTEGRATION_TOP_N", "10")))
    parser.add_argument("--max-workers", type=int, default=int(os.getenv("INTEGRATION_MAX_WORKERS", "2")))
    parser.add_argument("--min-final-score", type=float, default=float(os.getenv("INTEGRATION_MIN_FINAL_SCORE", "0.55")))
    parser.add_argument("--exchange", default=os.getenv("INTEGRATION_EXCHANGE", "NASDAQ"))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("INTEGRATION_TIMEOUT", "900")))
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Use execute=false. This is the default safe mode.")
    mode.add_argument("--execute", action="store_true", help="Use execute=true. Use only in PAPER/SIMULATOR environments.")
    args = parser.parse_args()

    execute = bool(args.execute)
    payload = {
        "account_id": args.account_id,
        "max_universe": args.max_universe,
        "top_n": args.top_n,
        "exchange": args.exchange,
        "max_workers": args.max_workers,
        "min_final_score": args.min_final_score,
        "execute": execute,
    }
    url = args.manager_url.rstrip("/") + "/discover-analyze-trade"
    print(f"Calling {url}")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    body = post_json(url, payload, timeout=args.timeout)
    assert_portfolio_contract(body, execute=execute)


if __name__ == "__main__":
    main()

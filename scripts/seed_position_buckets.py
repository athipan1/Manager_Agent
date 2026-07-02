from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

DEFAULT_ASSIGNMENTS = [
    {"symbol": "ADBE", "strategy_bucket": "core_dividend", "reason": "current known core bucket"},
    {"symbol": "ACGL", "strategy_bucket": "value_rebound", "reason": "current known value rebound bucket"},
    {"symbol": "BKNG", "strategy_bucket": "quality_growth", "reason": "high-quality growth compounder bucket"},
    {"symbol": "CINF", "strategy_bucket": "value_rebound", "reason": "current known value rebound bucket"},
]
VALID_BUCKETS = {"core_dividend", "quality_growth", "value_rebound", "news_momentum", "unassigned"}


def normalize_bucket(value: Any) -> str:
    bucket = str(value or "unassigned").strip().lower()
    return bucket if bucket in VALID_BUCKETS else "unassigned"


def load_assignments(raw_json: str | None = None, file_path: Path | None = None) -> List[Dict[str, Any]]:
    if file_path:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    elif raw_json:
        raw = json.loads(raw_json)
    else:
        raw = DEFAULT_ASSIGNMENTS
    if isinstance(raw, dict):
        raw = raw.get("assignments") or []
    output: List[Dict[str, Any]] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").strip().upper()
        bucket = normalize_bucket(item.get("strategy_bucket") or item.get("bucket"))
        if not symbol or bucket == "unassigned":
            continue
        output.append(
            {
                "symbol": symbol,
                "strategy_bucket": bucket,
                "source": item.get("source") or "manager_bucket_seed",
                "reason": item.get("reason") or "seeded by Manager_Agent bucket review workflow",
            }
        )
    return output


def request_json(base_url: str, path: str, *, payload: Any, api_key: str | None = None, timeout: int = 60) -> Dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-KEY"] = api_key
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {"status": "success", "data": None}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        return {"status": "error", "http_status": exc.code, "body": body}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def seed_position_buckets(database_url: str, account_id: str, assignments: List[Dict[str, Any]], api_key: str | None = None) -> Dict[str, Any]:
    payload = {"source": "manager_bucket_seed", "assignments": assignments}
    response = request_json(database_url, f"/accounts/{account_id}/position-buckets/bulk", payload=payload, api_key=api_key)
    return {"request": payload, "response": response, "assignment_count": len(assignments)}


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed Database_Agent position bucket labels before bucket review.")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_AGENT_URL", "http://localhost:8004"))
    parser.add_argument("--database-api-key", default=os.getenv("DATABASE_AGENT_API_KEY", ""))
    parser.add_argument("--account-id", default=os.getenv("DEFAULT_ACCOUNT_ID", "1"))
    parser.add_argument("--assignments-json", default=os.getenv("POSITION_BUCKET_ASSIGNMENTS", ""))
    parser.add_argument("--assignments-file", type=Path, default=None)
    parser.add_argument("--output-json", type=Path, default=Path("reports/position-bucket-seed.json"))
    parser.add_argument("--allow-empty", action="store_true")
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    assignments = load_assignments(args.assignments_json or None, args.assignments_file)
    result: Dict[str, Any]
    if not assignments and not args.allow_empty:
        result = {"status": "error", "error": "no valid bucket assignments"}
        exit_code = 1
    else:
        result = seed_position_buckets(args.database_url, str(args.account_id), assignments, api_key=args.database_api_key.strip() or None)
        response = result.get("response") or {}
        exit_code = 0 if response.get("status") != "error" else 1
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

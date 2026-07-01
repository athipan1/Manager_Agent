from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict


def get_json(base_url: str, path: str, api_key: str | None = None, timeout: int = 30) -> Dict[str, Any]:
    headers = {}
    if api_key:
        headers["X-API-KEY"] = api_key
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers=headers,
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        return {
            "status": "error",
            "http_status": exc.code,
            "body": exc.read().decode("utf-8", errors="replace"),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def unwrap(value: Dict[str, Any]) -> Dict[str, Any]:
    data = value.get("data")
    return data if isinstance(data, dict) else {}


def expected_review_run_id(store_result: Dict[str, Any]) -> str:
    request = store_result.get("request") or {}
    review_run_id = request.get("review_run_id")
    if not review_run_id:
        raise ValueError("review_run_id missing from store result request")
    return str(review_run_id)


def verify_history(store_result: Dict[str, Any], database_url: str, database_api_key: str | None) -> Dict[str, Any]:
    review_run_id = expected_review_run_id(store_result)
    response = get_json(database_url, f"/review-history/{review_run_id}", api_key=database_api_key)
    data = unwrap(response)
    decisions = data.get("decisions") or []
    request_report = (store_result.get("request") or {}).get("report") or {}
    expected_count = int((request_report.get("summary") or {}).get("reviewed_positions") or len(request_report.get("reviewed_positions") or []))
    verified = (
        response.get("status") == "success"
        and data.get("review_run_id") == review_run_id
        and len(decisions) == expected_count
    )
    return {
        "verified": verified,
        "review_run_id": review_run_id,
        "expected_decisions": expected_count,
        "stored_decisions": len(decisions),
        "response": response,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a stored bucket review history record in Database_Agent.")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_AGENT_URL", "http://localhost:8004"))
    parser.add_argument("--database-api-key", default=os.getenv("DATABASE_AGENT_API_KEY", "dev_database_key"))
    parser.add_argument("--input-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    store_result = json.loads(args.input_json.read_text(encoding="utf-8"))
    result = verify_history(store_result, args.database_url, args.database_api_key)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("verified") else 1


if __name__ == "__main__":
    raise SystemExit(main())

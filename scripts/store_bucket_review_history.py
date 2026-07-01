from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict


def post_json(base_url: str, path: str, payload: Dict[str, Any], api_key: str | None = None, timeout: int = 30) -> Dict[str, Any]:
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
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        return {
            "status": "error",
            "http_status": exc.code,
            "body": exc.read().decode("utf-8", errors="replace"),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def build_payload(report: Dict[str, Any], account_id: str | int = 1, source: str = "manager-agent") -> Dict[str, Any]:
    bucket = report.get("bucket") or "unassigned"
    generated_at = str(report.get("generated_at") or "unknown")
    safe_generated = generated_at.replace(":", "").replace("-", "").replace("+", "").replace(".", "")
    review_run_id = f"bucket-review-{bucket}-{safe_generated}"
    return {
        "account_id": account_id,
        "review_run_id": review_run_id,
        "bucket": bucket,
        "source": source,
        "status": "completed",
        "report": report,
    }


def store_history(report: Dict[str, Any], database_url: str, database_api_key: str | None, account_id: str | int = 1) -> Dict[str, Any]:
    payload = build_payload(report, account_id=account_id)
    response = post_json(database_url, "/review-history", payload, api_key=database_api_key)
    return {"request": payload, "response": response}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Store a final bucket review report in Database_Agent history.")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_AGENT_URL", "http://localhost:8004"))
    parser.add_argument("--database-api-key", default=os.getenv("DATABASE_AGENT_API_KEY", "dev_database_key"))
    parser.add_argument("--account-id", default=os.getenv("DEFAULT_ACCOUNT_ID", "1"))
    parser.add_argument("--input-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = json.loads(args.input_json.read_text(encoding="utf-8"))
    result = store_history(report, args.database_url, args.database_api_key, account_id=args.account_id)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if result.get("response", {}).get("status") == "error":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

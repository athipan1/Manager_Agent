from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional


def get_json(base_url: str, path: str, params: Optional[Dict[str, Any]] = None, api_key: str | None = None, timeout: int = 30) -> Dict[str, Any]:
    query = ""
    if params:
        filtered = {key: value for key, value in params.items() if value not in (None, "")}
        if filtered:
            query = "?" + urllib.parse.urlencode(filtered)
    headers = {}
    if api_key:
        headers["X-API-KEY"] = api_key
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}{query}",
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


def ticket_id_from_store_result(store_result: Dict[str, Any]) -> Optional[str]:
    response = store_result.get("response") if isinstance(store_result, dict) else {}
    data = response.get("data") if isinstance(response, dict) else {}
    if isinstance(data, dict) and data.get("ticket_id"):
        return str(data["ticket_id"])
    request = store_result.get("request") if isinstance(store_result, dict) else {}
    if isinstance(request, dict) and request.get("ticket_id"):
        return str(request["ticket_id"])
    return None


def fetch_order_review_ticket_audit_summary(
    database_url: str,
    database_api_key: str | None,
    account_id: str | int = 1,
    source: str = "manager-agent-hourly-workflow",
    latest_ticket_id: Optional[str] = None,
) -> Dict[str, Any]:
    params = {
        "account_id": account_id,
        "source": source,
        "latest_ticket_id": latest_ticket_id,
    }
    return get_json(database_url, "/order-review-tickets/summary", params=params, api_key=database_api_key)


def attach_summary_to_report(
    report: Dict[str, Any],
    summary_response: Dict[str, Any],
    store_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    updated = dict(report)
    updated["order_review_ticket_audit_summary"] = summary_response
    if store_result is not None:
        updated["order_review_ticket_store_result"] = store_result
    return updated


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch Database_Agent order review ticket audit summary and attach it to the hourly report.")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_AGENT_URL", "http://localhost:8004"))
    parser.add_argument("--database-api-key", default=os.getenv("DATABASE_AGENT_API_KEY", "dev_database_key"))
    parser.add_argument("--account-id", default=os.getenv("DEFAULT_ACCOUNT_ID", "1"))
    parser.add_argument("--source", default="manager-agent-hourly-workflow")
    parser.add_argument("--input-json", type=Path, required=True)
    parser.add_argument("--store-result-json", type=Path)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--summary-output-json", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = json.loads(args.input_json.read_text(encoding="utf-8"))
    store_result = None
    latest_ticket_id = None
    if args.store_result_json and args.store_result_json.exists():
        store_result = json.loads(args.store_result_json.read_text(encoding="utf-8"))
        latest_ticket_id = ticket_id_from_store_result(store_result)

    summary_response = fetch_order_review_ticket_audit_summary(
        args.database_url,
        args.database_api_key,
        account_id=args.account_id,
        source=args.source,
        latest_ticket_id=latest_ticket_id,
    )

    updated_report = attach_summary_to_report(report, summary_response, store_result=store_result)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(updated_report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    args.summary_output_json.parent.mkdir(parents=True, exist_ok=True)
    args.summary_output_json.write_text(json.dumps(summary_response, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary_response, ensure_ascii=False, indent=2, default=str))
    if summary_response.get("status") == "error":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


def request_json(base_url: str, path: str, *, method: str = "GET", payload: Any = None, api_key: str | None = None, timeout: int = 60) -> Any:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers: Dict[str, str] = {"Content-Type": "application/json"} if payload is not None else {}
    if api_key:
        headers["X-API-KEY"] = api_key
    req = urllib.request.Request(f"{base_url.rstrip('/')}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        return {"status": "error", "http_status": exc.code, "body": exc.read().decode("utf-8", errors="replace")}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def unwrap(value: Any) -> Any:
    return value.get("data") if isinstance(value, dict) and "data" in value else value


def fetch_runtime_state(execution_url: str, execution_api_key: str | None) -> Dict[str, Any]:
    account = request_json(execution_url, "/account", api_key=execution_api_key)
    positions = unwrap(request_json(execution_url, "/positions", api_key=execution_api_key)) or []
    items = unwrap(request_json(execution_url, "/orders", api_key=execution_api_key)) or []
    return {"account": account, "positions": positions, "open_orders": items}


def post_database_snapshot(database_url: str, account_id: str, state: Dict[str, Any], database_api_key: str | None) -> Dict[str, Any]:
    payload = {
        "account_id": int(account_id),
        "broker": "ALPACA",
        "paper": True,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "account": unwrap(state.get("account")) or {},
        "positions": state.get("positions") or [],
        "open_orders": state.get("open_orders") or [],
        "summary": {
            "position_count": len(state.get("positions") or []),
            "open_order_count": len(state.get("open_orders") or []),
            "source": "manager_bucket_review_prepare",
        },
    }
    response = request_json(database_url, "/broker-sync/snapshot", method="POST", payload=payload, api_key=database_api_key)
    return {"payload_summary": payload["summary"], "response": response}


def parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare Database_Agent positions before bucket review.")
    parser.add_argument("--execution-url", default=os.getenv("EXECUTION_AGENT_URL", "http://localhost:8006"))
    parser.add_argument("--execution-api-key", default=os.getenv("EXECUTION_API_KEY", ""))
    parser.add_argument("--database-url", default=os.getenv("DATABASE_AGENT_URL", "http://localhost:8004"))
    parser.add_argument("--database-api-key", default=os.getenv("DATABASE_AGENT_API_KEY", ""))
    parser.add_argument("--account-id", default=os.getenv("DEFAULT_ACCOUNT_ID", "1"))
    parser.add_argument("--output-json", type=Path, default=Path("reports/database-position-prepare.json"))
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    state = fetch_runtime_state(args.execution_url, args.execution_api_key.strip() or None)
    result = post_database_snapshot(args.database_url, str(args.account_id), state, args.database_api_key.strip() or None)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    response = result.get("response") or {}
    return 0 if response.get("status") != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())

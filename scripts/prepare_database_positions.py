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


def _checked_runtime_payload(response: Any, path: str, *, expect_list: bool) -> Any:
    """Fail closed on an execution error; never interpret errors as broker rows."""
    if isinstance(response, dict):
        # Execution_Agent uses status="success" in its response envelope, while
        # an unwrapped Alpaca account legitimately contains status="ACTIVE".
        # Distinguish those shapes so an authenticated Paper snapshot is not
        # rejected during the second validation at the persistence boundary.
        status = response.get("status")
        is_envelope = "data" in response
        if (
            response.get("error")
            or response.get("http_status") is not None
            or status in ("error", "failed", "failure")
            or (is_envelope and status not in (None, "success"))
        ):
            raise ValueError(f"{path}: Execution_Agent returned an error; snapshot refused")
    value = unwrap(response)
    if expect_list:
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise ValueError(f"{path}: expected a list of broker objects; snapshot refused")
    elif not isinstance(value, dict) or value.get("cash") in (None, ""):
        raise ValueError(f"{path}: missing verified account cash; snapshot refused")
    return value


def fetch_runtime_state(execution_url: str, execution_api_key: str | None) -> Dict[str, Any]:
    account = request_json(execution_url, "/account", api_key=execution_api_key)
    account = _checked_runtime_payload(account, "/account", expect_list=False)
    positions = _checked_runtime_payload(
        request_json(execution_url, "/positions", api_key=execution_api_key),
        "/positions",
        expect_list=True,
    )
    items = _checked_runtime_payload(
        request_json(execution_url, "/orders", api_key=execution_api_key),
        "/orders",
        expect_list=True,
    )
    return {"account": account, "positions": positions, "open_orders": items}


def post_database_snapshot(database_url: str, account_id: str, state: Dict[str, Any], database_api_key: str | None) -> Dict[str, Any]:
    # Validate again at the persistence boundary to protect direct callers.
    _checked_runtime_payload(state.get("account"), "/account", expect_list=False)
    _checked_runtime_payload(state.get("positions"), "/positions", expect_list=True)
    _checked_runtime_payload(state.get("open_orders"), "/orders", expect_list=True)
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
    snapshot_written = False  # None means a POST occurred but confirmation is missing.
    try:
        state = fetch_runtime_state(args.execution_url, args.execution_api_key.strip() or None)
        result = post_database_snapshot(args.database_url, str(args.account_id), state, args.database_api_key.strip() or None)
        snapshot_written = None
        response = result.get("response") or {}
        if response.get("status") != "success":
            raise ValueError("Database_Agent snapshot was not confirmed successful")
        exit_code = 0
    except ValueError as exc:
        result = {"status": "error", "reason": str(exc), "snapshot_written": snapshot_written}
        exit_code = 1
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

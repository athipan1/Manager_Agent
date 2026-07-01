from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List


def request_json(base_url: str, path: str, payload: Dict[str, Any], api_key: str | None = None, timeout: int = 30) -> Dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["X-API-KEY"] = api_key
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        return {"status": "error", "http_status": exc.code, "body": exc.read().decode("utf-8", errors="replace")}
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def unwrap(value: Any) -> Any:
    return value.get("data") if isinstance(value, dict) and "data" in value else value


def first_profit_action(row: Dict[str, Any]) -> Dict[str, Any]:
    plan = row.get("profit_plan") or {}
    actions = plan.get("actions") or []
    if actions and isinstance(actions[0], dict):
        return actions[0]
    return {
        "action": plan.get("primary_action") or "hold",
        "symbol": row.get("symbol"),
        "quantity": 0,
        "reason": "No profit action payload was present; defaulted to hold preview.",
    }


def build_preview_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    profit_request = row.get("profit_request") or {}
    position = profit_request.get("position") or {}
    risk_result = row.get("risk_result") or {}
    return {
        "position": {
            "symbol": row.get("symbol") or position.get("symbol"),
            "side": "long",
            "quantity": position.get("quantity") or row.get("quantity") or 0,
            "entry_price": position.get("entry_price") or row.get("entry_price") or 0,
            "current_price": position.get("current_price") or row.get("current_price") or 0,
            "stop_loss": position.get("stop_loss") or row.get("stop_loss"),
            "strategy_bucket": row.get("bucket") or "unassigned",
        },
        "action": first_profit_action(row),
        "risk_result": risk_result,
        "dry_run": True,
        "manual_approval_required": True,
    }


def apply_execution_preview(report: Dict[str, Any], execution_url: str, execution_api_key: str | None = None) -> Dict[str, Any]:
    reviewed: List[Dict[str, Any]] = report.get("reviewed_positions") or []
    submitted = 0
    preview_ready = 0
    blocked = 0
    for row in reviewed:
        if row.get("risk_status") != "approved":
            row["execution_preview_status"] = "skipped_risk_not_approved"
            row["execution_preview_result"] = None
            continue
        payload = build_preview_payload(row)
        response = request_json(
            execution_url,
            "/execution/profit-action-preview",
            payload,
            api_key=execution_api_key,
        )
        data = unwrap(response) or {}
        row["execution_preview_request"] = payload
        row["execution_preview_result"] = data
        row["execution_preview_status"] = "ready" if data.get("approved_for_execution") else "blocked"
        submitted += 1
        if row["execution_preview_status"] == "ready":
            preview_ready += 1
        else:
            blocked += 1
    summary = report.setdefault("summary", {})
    summary["execution_preview_submissions"] = submitted
    summary["execution_preview_ready"] = preview_ready
    summary["execution_preview_blocked"] = blocked
    summary["execution_submissions"] = 0
    safety = report.setdefault("safety", {})
    safety["execution_agent_preview_submitted"] = submitted > 0
    safety["execution_agent_submitted"] = False
    safety["orders_submitted"] = False
    return report


def render_summary(report: Dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Execution Profit Preview Report",
        "",
        f"Bucket: `{report.get('bucket', '-')}`",
        f"Reviewed Positions: `{summary.get('reviewed_positions', 0)}`",
        f"Execution Preview Submissions: `{summary.get('execution_preview_submissions', 0)}`",
        f"Execution Preview Ready: `{summary.get('execution_preview_ready', 0)}`",
        f"Execution Preview Blocked: `{summary.get('execution_preview_blocked', 0)}`",
        f"Orders Submitted: `{str((report.get('safety') or {}).get('orders_submitted', False)).lower()}`",
        "",
        "| Symbol | Profit Action | Risk Status | Preview Status |",
        "|---|---|---|---|",
    ]
    for row in report.get("reviewed_positions") or []:
        action = ((row.get("profit_plan") or {}).get("primary_action") or "-")
        lines.append(f"| {row.get('symbol', '-')} | {action} | {row.get('risk_status', '-')} | {row.get('execution_preview_status', '-')} |")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply Execution_Agent profit-action preview to a risk-gated bucket review report.")
    parser.add_argument("--execution-url", default=os.getenv("EXECUTION_AGENT_URL", "http://localhost:8006"))
    parser.add_argument("--execution-api-key", default=os.getenv("EXECUTION_API_KEY", "dev_execution_key"))
    parser.add_argument("--input-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = json.loads(args.input_json.read_text(encoding="utf-8"))
    updated = apply_execution_preview(report, args.execution_url, args.execution_api_key)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(updated, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if args.output_md:
        args.output_md.write_text(render_summary(updated), encoding="utf-8")
    print(render_summary(updated))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

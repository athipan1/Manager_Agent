from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


def get_json(base_url: str, path: str, api_key: Optional[str] = None, timeout: int = 30) -> Dict[str, Any]:
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


def latest_summary_path(account_id: str | int | None = None, bucket: str | None = None) -> str:
    params = {}
    if account_id:
        params["account_id"] = str(account_id)
    if bucket:
        params["bucket"] = str(bucket)
    query = urllib.parse.urlencode(params)
    return f"/review-history/latest?{query}" if query else "/review-history/latest"


def fetch_latest_summary(database_url: str, database_api_key: Optional[str], account_id: str | int | None, bucket: str | None) -> Dict[str, Any]:
    response = get_json(database_url, latest_summary_path(account_id=account_id, bucket=bucket), api_key=database_api_key)
    return {
        "request": {
            "database_url": database_url,
            "account_id": str(account_id) if account_id is not None else None,
            "bucket": bucket,
        },
        "response": response,
        "summary": response.get("data") if response.get("status") == "success" else None,
    }


def _fmt_counts(counts: Dict[str, Any]) -> str:
    if not counts:
        return "-"
    return ", ".join(f"{key}: {value}" for key, value in sorted(counts.items()))


def _decision_rows(decisions: Iterable[Dict[str, Any]]) -> list[str]:
    rows = ["| Symbol | Profit Action | Risk | Preview | Final Decision | Reason |", "|---|---|---|---|---|---|"]
    for item in decisions:
        rows.append(
            "| {symbol} | {profit_action} | {risk_status} | {preview_status} | {final_decision} | {reason} |".format(
                symbol=item.get("symbol") or "-",
                profit_action=item.get("profit_action") or "-",
                risk_status=item.get("risk_status") or "-",
                preview_status=item.get("preview_status") or "-",
                final_decision=item.get("final_decision") or "-",
                reason=str(item.get("reason") or "-").replace("|", "/"),
            )
        )
    return rows


def render_markdown(result: Dict[str, Any]) -> str:
    response = result.get("response") or {}
    summary = result.get("summary") or {}
    if response.get("status") != "success" or not summary:
        return "\n".join([
            "# Latest Review History Summary",
            "",
            "Status: `error`",
            "",
            "```json",
            json.dumps(response, ensure_ascii=False, indent=2, default=str),
            "```",
            "",
        ])

    lines = [
        f"# Latest Review History Summary — {summary.get('bucket', 'unknown')}",
        "",
        f"Latest review run: `{summary.get('latest_review_run_id')}`",
        f"Generated at: `{summary.get('generated_at')}`",
        f"Status: `{summary.get('status')}`",
        f"Mode: `{summary.get('mode')}`",
        "",
        "## Summary",
        f"- Positions seen: `{summary.get('positions_seen', 0)}`",
        f"- Reviewed positions: `{summary.get('reviewed_positions', 0)}`",
        f"- Database bucket hints applied: `{summary.get('database_bucket_hints_applied', 0)}`",
        f"- Profit Agent used: `{summary.get('profit_agent_used', 0)}`",
        f"- Risk approved: `{summary.get('risk_approved', 0)}`",
        f"- Risk rejected: `{summary.get('risk_rejected', 0)}`",
        f"- Preview ready: `{summary.get('execution_preview_ready', 0)}`",
        f"- Preview blocked: `{summary.get('execution_preview_blocked', 0)}`",
        "",
        "## Safety",
        f"- Advisory only: `{str(summary.get('advisory_only', True)).lower()}`",
        f"- Orders submitted: `{str(summary.get('orders_submitted', False)).lower()}`",
        f"- Execution submissions: `{summary.get('execution_submissions', 0)}`",
        "",
        "## Counts",
        f"- Final decisions: `{_fmt_counts(summary.get('final_decisions') or {})}`",
        f"- Profit actions: `{_fmt_counts(summary.get('profit_actions') or {})}`",
        f"- Risk statuses: `{_fmt_counts(summary.get('risk_statuses') or {})}`",
        f"- Preview statuses: `{_fmt_counts(summary.get('preview_statuses') or {})}`",
        "",
        "## Decisions",
        *_decision_rows(summary.get("decisions") or []),
        "",
        "## Compact JSON",
        "```json",
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render the latest review history summary from Database_Agent.")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_AGENT_URL", "http://localhost:8004"))
    parser.add_argument("--database-api-key", default=os.getenv("DATABASE_AGENT_API_KEY", "dev_database_key"))
    parser.add_argument("--account-id", default=os.getenv("DEFAULT_ACCOUNT_ID", "1"))
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = fetch_latest_summary(args.database_url, args.database_api_key, account_id=args.account_id, bucket=args.bucket)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    args.output_md.write_text(render_markdown(result), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result.get("response", {}).get("status") == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())

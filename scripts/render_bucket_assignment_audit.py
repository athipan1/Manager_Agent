from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

UNASSIGNED = "unassigned"


def unwrap(value: Any) -> Any:
    return value.get("data") if isinstance(value, dict) and "data" in value else value


def get_json(base_url: str, path: str, api_key: Optional[str] = None, timeout: int = 30) -> Any:
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
            return json.loads(body) if body else None
    except urllib.error.HTTPError as exc:
        return {
            "status": "error",
            "http_status": exc.code,
            "body": exc.read().decode("utf-8", errors="replace"),
        }
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def symbol(row: Dict[str, Any]) -> str:
    return str(row.get("symbol") or row.get("ticker") or "").upper().strip()


def normalize_bucket(value: Any) -> str:
    bucket = str(value or "").strip().lower()
    return bucket if bucket else UNASSIGNED


def positions_from_response(response: Any) -> list[Dict[str, Any]]:
    data = unwrap(response)
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict) and symbol(row)]
    if isinstance(data, dict):
        rows = unwrap(data.get("positions")) or []
        return [row for row in rows if isinstance(row, dict) and symbol(row)]
    return []


def bucket_hints_from_response(response: Any) -> dict[str, dict[str, str]]:
    data = unwrap(response)
    hints: dict[str, dict[str, str]] = {}
    if not isinstance(data, list):
        return hints
    for row in data:
        if not isinstance(row, dict):
            continue
        sym = symbol(row)
        if not sym:
            continue
        bucket = normalize_bucket(row.get("strategy_bucket") or row.get("bucket"))
        hints[sym] = {
            "bucket": bucket,
            "source": str(row.get("strategy_bucket_source") or row.get("source") or "database_agent"),
            "reason": str(row.get("strategy_bucket_reason") or row.get("reason") or ""),
        }
    return hints


def bucket_distribution(rows: Iterable[Dict[str, Any]]) -> dict[str, int]:
    output: dict[str, int] = {}
    for row in rows:
        bucket = normalize_bucket(row.get("bucket"))
        output[bucket] = output.get(bucket, 0) + 1
    return dict(sorted(output.items()))


def build_assignment_audit(positions: list[Dict[str, Any]], hints: dict[str, dict[str, str]]) -> Dict[str, Any]:
    rows = []
    for position in sorted(positions, key=symbol):
        sym = symbol(position)
        hint = hints.get(sym) or {}
        fallback_bucket = normalize_bucket(position.get("strategy_bucket") or position.get("bucket") or position.get("bucket_name"))
        bucket = normalize_bucket(hint.get("bucket") or fallback_bucket)
        source = hint.get("source") or position.get("strategy_bucket_source") or "position_data"
        rows.append({
            "symbol": sym,
            "bucket": bucket,
            "bucket_source": source if bucket != UNASSIGNED else "missing",
            "quantity": position.get("qty") or position.get("quantity"),
            "reason": hint.get("reason") or position.get("strategy_bucket_reason") or "",
        })
    unassigned = [row for row in rows if row.get("bucket") == UNASSIGNED]
    assigned = [row for row in rows if row.get("bucket") != UNASSIGNED]
    return {
        "positions_seen": len(rows),
        "assigned_positions": len(assigned),
        "unassigned_positions_count": len(unassigned),
        "bucket_distribution": bucket_distribution(rows),
        "unassigned_positions": unassigned,
        "positions": rows,
        "action_required": len(unassigned) > 0,
    }


def fetch_assignment_audit(execution_url: str, execution_api_key: Optional[str], database_url: str, database_api_key: Optional[str], account_id: str | int) -> Dict[str, Any]:
    positions_response = get_json(execution_url, "/positions", api_key=execution_api_key)
    bucket_response = get_json(database_url, f"/accounts/{account_id}/position-buckets", api_key=database_api_key)
    positions = positions_from_response(positions_response)
    hints = bucket_hints_from_response(bucket_response)
    audit = build_assignment_audit(positions, hints)
    return {
        "request": {
            "execution_url": execution_url,
            "database_url": database_url,
            "account_id": str(account_id),
        },
        "source_status": {
            "positions_status": positions_response.get("status") if isinstance(positions_response, dict) else "success",
            "bucket_hints_status": bucket_response.get("status") if isinstance(bucket_response, dict) else "success",
        },
        **audit,
    }


def render_markdown(audit: Dict[str, Any]) -> str:
    lines = [
        "# Bucket Assignment Audit",
        "",
        "## Summary",
        f"- Positions seen: `{audit.get('positions_seen', 0)}`",
        f"- Assigned positions: `{audit.get('assigned_positions', 0)}`",
        f"- Unassigned positions: `{audit.get('unassigned_positions_count', 0)}`",
        f"- Action required: `{str(audit.get('action_required', False)).lower()}`",
        "",
        "## Bucket Distribution",
        "```json",
        json.dumps(audit.get("bucket_distribution") or {}, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## Unassigned Positions",
    ]
    unassigned = audit.get("unassigned_positions") or []
    if not unassigned:
        lines.append("No unassigned open positions found.")
    else:
        lines.append("| Symbol | Qty | Current Bucket | Source |")
        lines.append("|---|---:|---|---|")
        for row in unassigned:
            lines.append(f"| {row.get('symbol', '-')} | {row.get('quantity', '-')} | {row.get('bucket', UNASSIGNED)} | {row.get('bucket_source', 'missing')} |")
    lines.extend([
        "",
        "## All Positions",
        "| Symbol | Qty | Bucket | Source | Reason |",
        "|---|---:|---|---|---|",
    ])
    for row in audit.get("positions") or []:
        reason = str(row.get("reason") or "-").replace("|", "/")
        lines.append(f"| {row.get('symbol', '-')} | {row.get('quantity', '-')} | {row.get('bucket', '-')} | {row.get('bucket_source', '-')} | {reason} |")
    lines.extend([
        "",
        "## Compact JSON",
        "```json",
        json.dumps(audit, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
    ])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render bucket assignment audit for open positions.")
    parser.add_argument("--execution-url", default=os.getenv("EXECUTION_AGENT_URL", "http://localhost:8006"))
    parser.add_argument("--execution-api-key", default=os.getenv("EXECUTION_API_KEY", "dev_execution_key"))
    parser.add_argument("--database-url", default=os.getenv("DATABASE_AGENT_URL", "http://localhost:8004"))
    parser.add_argument("--database-api-key", default=os.getenv("DATABASE_AGENT_API_KEY", "dev_database_key"))
    parser.add_argument("--account-id", default=os.getenv("DEFAULT_ACCOUNT_ID", "1"))
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    audit = fetch_assignment_audit(
        args.execution_url,
        args.execution_api_key,
        args.database_url,
        args.database_api_key,
        args.account_id,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(audit, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    args.output_md.write_text(render_markdown(audit), encoding="utf-8")
    print(args.output_md.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

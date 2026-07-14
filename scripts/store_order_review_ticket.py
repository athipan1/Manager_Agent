from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional


def unwrap_data(value: Any) -> Any:
    if isinstance(value, dict) and "data" in value:
        return value.get("data")
    return value


def _error_text(value: Any) -> Optional[str]:
    """Return the most useful human-readable error detail from nested JSON."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            decoded = json.loads(text)
        except (TypeError, ValueError):
            return text
        return _error_text(decoded) or text
    if isinstance(value, dict):
        for key in ("message", "detail", "reason", "description"):
            text = _error_text(value.get(key))
            if text:
                return text
        for key in ("error", "details", "errors", "body"):
            text = _error_text(value.get(key))
            if text:
                return text
        if value:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
        return None
    if isinstance(value, list):
        parts = [text for item in value if (text := _error_text(item))]
        return "; ".join(parts) if parts else None
    return str(value)


def manager_flow_failure(report: Dict[str, Any]) -> Optional[str]:
    """Describe a failed Manager discovery response, or return None on success."""
    response = report.get("response")
    if not isinstance(response, dict):
        return "Manager discover-analyze-trade response is missing or invalid."
    if response.get("status") == "success":
        return None

    http_status = response.get("http_status")
    detail = (
        _error_text(response.get("body"))
        or _error_text(response.get("error"))
        or _error_text(response)
        or "No error details provided."
    )
    prefix = "Manager discover-analyze-trade failed"
    if http_status is not None:
        prefix += f" (HTTP {http_status})"
    return f"{prefix}: {detail}"


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


def ticket_from_report(report: Dict[str, Any]) -> Dict[str, Any]:
    ticket_response = report.get("order_review_approval_ticket") or {}
    ticket = unwrap_data(ticket_response) or {}
    return ticket if isinstance(ticket, dict) else {}


def _summary(ticket: Dict[str, Any]) -> Dict[str, Any]:
    summary = ticket.get("summary")
    return summary if isinstance(summary, dict) else {}


def build_payload(
    report: Dict[str, Any],
    account_id: str | int = 1,
    source: str = "manager-agent-hourly-workflow",
) -> Dict[str, Any]:
    ticket = ticket_from_report(report)
    summary = _summary(ticket)
    ticket_id = ticket.get("ticket_id")
    if not ticket_id:
        generated_at = str(report.get("generated_at") or "unknown")
        safe_generated = generated_at.replace(":", "").replace("-", "").replace("+", "").replace(".", "")
        ticket_id = f"order-review-ticket-missing-{safe_generated}"

    ready_count = summary.get("ready_for_manual_approval_count", 0)
    blocked_count = summary.get("blocked_count", 0)
    status = "blocked" if blocked_count else "ready_for_manual_approval" if ready_count else "created"

    return {
        "ticket_id": ticket_id,
        "account_id": account_id,
        "source": source,
        "mode": ticket.get("mode") or "manual_approval_ticket",
        "safety": ticket.get("safety") or "read_only_no_orders_submitted_no_orders_cancelled",
        "status": status,
        "approval_required": bool(ticket.get("approval_required", True)),
        "execution_enabled": bool(ticket.get("execution_enabled", False)),
        "manual_confirmation_phrase": ticket.get("manual_confirmation_phrase"),
        "requested_symbols": ticket.get("requested_symbols") or [],
        "ready_count": int(ready_count or 0),
        "blocked_count": int(blocked_count or 0),
        "orders_submitted": bool(summary.get("orders_submitted", False)),
        "orders_cancelled": bool(summary.get("orders_cancelled", False)),
        "ticket_payload": report.get("order_review_approval_ticket") or {},
        "metadata": {
            "generated_at": report.get("generated_at"),
            "mode": report.get("mode"),
            "broker_mode": report.get("broker_mode"),
            "flow": report.get("flow"),
            "workflow": "hourly-auto-trading",
        },
    }


def fetch_order_review_ticket_audit_summary(
    database_url: str,
    database_api_key: str | None,
    account_id: str | int = 1,
    source: str = "manager-agent-hourly-workflow",
    latest_ticket_id: Optional[str] = None,
) -> Dict[str, Any]:
    return get_json(
        database_url,
        "/order-review-tickets/summary",
        params={
            "account_id": account_id,
            "source": source,
            "latest_ticket_id": latest_ticket_id,
        },
        api_key=database_api_key,
    )


def store_order_review_ticket(
    report: Dict[str, Any],
    database_url: str,
    database_api_key: str | None,
    account_id: str | int = 1,
    source: str = "manager-agent-hourly-workflow",
    include_summary: bool = True,
) -> Dict[str, Any]:
    payload = build_payload(report, account_id=account_id, source=source)
    response = post_json(database_url, "/order-review-tickets", payload, api_key=database_api_key)
    result = {"request": payload, "response": response}
    if include_summary and response.get("status") != "error":
        result["audit_summary"] = fetch_order_review_ticket_audit_summary(
            database_url,
            database_api_key,
            account_id=account_id,
            source=source,
            latest_ticket_id=payload.get("ticket_id"),
        )
    return result


def attach_audit_to_report(report: Dict[str, Any], store_result: Dict[str, Any]) -> Dict[str, Any]:
    updated = dict(report)
    updated["order_review_ticket_store_result"] = store_result
    audit_summary = store_result.get("audit_summary")
    if audit_summary is not None:
        updated["order_review_ticket_audit_summary"] = audit_summary
    return updated


def render_audit_summary_markdown(summary_response: Dict[str, Any], store_result: Dict[str, Any]) -> str:
    summary = unwrap_data(summary_response) or {}
    latest = summary.get("latest_ticket") if isinstance(summary, dict) else {}
    if not isinstance(latest, dict):
        latest = {}
    response = store_result.get("response") if isinstance(store_result, dict) else {}
    lines = [
        "# Order Review Ticket Audit Summary",
        "",
        f"- Store Status: `{response.get('status', '-') if isinstance(response, dict) else '-'}`",
        f"- Total Tickets: `{summary.get('total_count', 0) if isinstance(summary, dict) else 0}`",
        f"- Ready Tickets: `{summary.get('ready_ticket_count', 0) if isinstance(summary, dict) else 0}`",
        f"- Blocked Tickets: `{summary.get('blocked_ticket_count', 0) if isinstance(summary, dict) else 0}`",
        f"- Approval Required Count: `{summary.get('approval_required_count', 0) if isinstance(summary, dict) else 0}`",
        f"- Execution Enabled Count: `{summary.get('execution_enabled_count', 0) if isinstance(summary, dict) else 0}`",
        f"- Total Ready Items: `{summary.get('total_ready_items', 0) if isinstance(summary, dict) else 0}`",
        f"- Total Blocked Items: `{summary.get('total_blocked_items', 0) if isinstance(summary, dict) else 0}`",
        "",
        "## Latest Ticket",
        f"- Ticket ID: `{latest.get('ticket_id', '-')}`",
        f"- Status: `{latest.get('status', '-')}`",
        f"- Ready Count: `{latest.get('ready_count', '-')}`",
        f"- Blocked Count: `{latest.get('blocked_count', '-')}`",
        f"- Approval Required: `{latest.get('approval_required', '-')}`",
        f"- Execution Enabled: `{latest.get('execution_enabled', '-')}`",
        f"- Created At: `{latest.get('created_at', '-')}`",
        f"- Updated At: `{latest.get('updated_at', '-')}`",
        "",
        "## Safety",
        "Audit summary is read-only and does not perform broker actions.",
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Store the hourly order review ticket in Database_Agent audit history.")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_AGENT_URL", "http://localhost:8004"))
    parser.add_argument("--database-api-key", default=os.getenv("DATABASE_AGENT_API_KEY", "dev_database_key"))
    parser.add_argument("--account-id", default=os.getenv("DEFAULT_ACCOUNT_ID", "1"))
    parser.add_argument("--source", default="manager-agent-hourly-workflow")
    parser.add_argument("--input-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = json.loads(args.input_json.read_text(encoding="utf-8"))

    failure_reason = manager_flow_failure(report)
    if failure_reason:
        validation = {
            "status": "error",
            "stage": "discover_analyze_trade",
            "reason": failure_reason,
            "store_skipped": True,
        }
        report["workflow_validation"] = validation
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(validation, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        args.input_json.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(json.dumps(validation, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1

    result = store_order_review_ticket(
        report,
        args.database_url,
        args.database_api_key,
        account_id=args.account_id,
        source=args.source,
    )
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    updated_report = attach_audit_to_report(report, result)
    args.input_json.write_text(json.dumps(updated_report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    audit_summary = result.get("audit_summary")
    if isinstance(audit_summary, dict):
        summary_markdown_path = args.output_json.parent / "order-review-ticket-audit-summary.md"
        summary_markdown_path.write_text(render_audit_summary_markdown(audit_summary, result), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if result.get("response", {}).get("status") == "error":
        return 1
    if result.get("audit_summary", {}).get("status") == "error":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

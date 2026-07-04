import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def unwrap_data(value: Any) -> Any:
    if isinstance(value, dict) and "data" in value:
        return value.get("data")
    return value


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _status_icon(status: Any) -> str:
    return {
        "validated": "✅",
        "validated_for_manual_review": "✅",
        "blocked": "⛔",
        "blocked_validation_failed": "⛔",
        "blocked_symbol_not_ready_in_ticket": "⛔",
        "skipped": "ℹ️",
    }.get(str(status or "").lower(), "ℹ️")


def render_manual_review_gate(lines: List[str], gate_response: Dict[str, Any]) -> None:
    if not gate_response:
        return

    gate = unwrap_data(gate_response) or {}
    if not isinstance(gate, dict):
        return

    if gate_response.get("status") == "skipped" or gate.get("status") == "skipped":
        lines.append("## Broker Manual Review Gate")
        lines.append("- Status: `skipped`")
        lines.append(f"- Reason: {gate_response.get('reason') or gate.get('reason') or '-'}")
        lines.append("")
        return

    summary = _dict(gate.get("summary"))
    symbols = _list(gate.get("symbols"))
    global_checks = _list(gate.get("global_checks"))

    if not summary and not symbols and not global_checks:
        return

    lines.append("## Broker Manual Review Gate")
    lines.append(f"- Status: `{gate.get('status', '-')}`")
    lines.append(f"- Mode: `{gate.get('mode', '-')}`")
    lines.append(f"- Safety: `{gate.get('safety', '-')}`")
    lines.append(f"- Ticket ID: `{gate.get('ticket_id', '-')}`")
    lines.append(f"- Approval Valid: `{gate.get('approval_valid', False)}`")
    lines.append(f"- Execution Enabled: `{gate.get('execution_enabled', False)}`")
    lines.append(f"- Requested Symbols: `{', '.join(gate.get('requested_symbols') or []) or '-'}`")
    lines.append(f"- Validated Symbols: `{summary.get('validated_symbol_count', 0)}`")
    lines.append(f"- Blocked Symbols: `{summary.get('blocked_symbol_count', 0)}`")
    lines.append(f"- Orders Changed By Gate: `{summary.get('orders_changed', False)}`")
    lines.append(f"- Next Step: `{gate.get('next_step', '-')}`")
    lines.append("")

    if symbols:
        lines.append("| Symbol | Gate Status | Valid | Qty | Current Stop Order | Stop | TP | Orders Changed |")
        lines.append("|---|---|---|---:|---|---:|---:|---|")
        for row in symbols:
            row = _dict(row)
            status = row.get("status", "-")
            lines.append(
                f"| {row.get('symbol', '-')} | {_status_icon(status)} `{status}` | "
                f"{row.get('valid', False)} | {row.get('qty', '-')} | "
                f"{row.get('current_stop_order_id', '-')} | {row.get('stop_price', '-')} | "
                f"{row.get('take_profit_price', '-')} | {row.get('orders_changed', False)} |"
            )
        lines.append("")

    failed_checks = []
    for check in global_checks:
        check = _dict(check)
        if check.get("passed") is not True:
            failed_checks.append(check)
    for row in symbols:
        for check in _list(_dict(row).get("checks")):
            check = _dict(check)
            if check.get("passed") is not True:
                failed_checks.append({"name": f"{_dict(row).get('symbol', '-')}.{check.get('name', '-')}", "detail": check.get("detail", "-")})

    if failed_checks:
        lines.append("### Manual Review Gate Attention Required")
        lines.append("| Check | Detail |")
        lines.append("|---|---|")
        for check in failed_checks[:12]:
            lines.append(f"| {check.get('name', '-')} | {check.get('detail', '-')} |")
        lines.append("")
    else:
        lines.append("### Manual Review Gate Safety")
        lines.append("Gate นี้เป็น paper-only validation เท่านั้น ไม่ cancel/replace/submit order จริง")
        lines.append("")


def append_manual_review_gate_report(report_path: Path, markdown_path: Path) -> None:
    raw = json.loads(report_path.read_text(encoding="utf-8"))
    lines: List[str] = []
    render_manual_review_gate(lines, raw.get("manual_review_gate") or {})
    if not lines:
        return
    existing = markdown_path.read_text(encoding="utf-8") if markdown_path.exists() else ""
    separator = "\n" if existing.endswith("\n") or not existing else "\n\n"
    markdown_path.write_text(existing + separator + "\n".join(lines), encoding="utf-8")


def main() -> int:
    report_path = Path("reports/hourly-auto-trading-report.json")
    markdown_path = Path("reports/hourly-auto-trading-report.md")
    if not report_path.exists():
        print(f"missing {report_path}", file=sys.stderr)
        return 1
    append_manual_review_gate_report(report_path, markdown_path)
    print(markdown_path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

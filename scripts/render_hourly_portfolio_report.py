import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

# GitHub Actions invokes this file as `python scripts/render_hourly_portfolio_report.py`.
# In that execution mode Python puts `scripts/` on sys.path, not the repository
# root, so imports from `app` fail unless the root is added explicitly.
_REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

try:
    from scripts.render_hourly_portfolio_report_legacy import *  # noqa: F401,F403
    import scripts.render_hourly_portfolio_report_legacy as _legacy
except ModuleNotFoundError:
    from render_hourly_portfolio_report_legacy import *  # type: ignore # noqa: F401,F403
    import render_hourly_portfolio_report_legacy as _legacy  # type: ignore


def _load_curator_summarizer():
    """Load the pure report helper without requiring the FastAPI runtime.

    The hourly workflow renders reports on the GitHub runner after the trading
    stack has finished.  That runner intentionally does not install the
    Manager application dependencies, so importing ``app.services`` would run
    ``app/__init__.py`` and fail when FastAPI is unavailable.  The observability
    module itself only uses the Python standard library and is safe to load
    directly in that environment.
    """
    try:
        from app.services.curator_observability import summarize_curator_signals

        return summarize_curator_signals
    except ModuleNotFoundError as exc:
        if exc.name != "fastapi":
            raise

    module_path = _REPOSITORY_ROOT / "app" / "services" / "curator_observability.py"
    spec = importlib.util.spec_from_file_location(
        "manager_curator_observability_report_helper",
        module_path,
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"unable to load curator report helper from {module_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.summarize_curator_signals


summarize_curator_signals = _load_curator_summarizer()


_legacy_render_curator_signals = _legacy.render_curator_signals


def _percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "-"


def render_curator_signals(lines: List[str], data: Dict[str, Any]) -> None:
    curator_signals = _legacy._list(data.get("curator_signals"))
    if not curator_signals:
        return

    summary = data.get("curator_ensemble_summary")
    if not isinstance(summary, dict):
        summary = summarize_curator_signals(curator_signals)
    if summary.get("mode") != "shadow_ensemble":
        _legacy_render_curator_signals(lines, data)
        return

    counts = _legacy._dict(summary.get("signal_counts"))
    rows = _legacy._list(summary.get("rows"))
    lines.append("## Curator Shadow Ensemble")
    lines.append("- Deployment Mode: `advisory`")
    lines.append(f"- Observations: `{summary.get('ensemble_observations', 0)}`")
    lines.append(
        f"- Available / Unavailable: `{summary.get('available', 0)}` / "
        f"`{summary.get('unavailable', 0)}`"
    )
    lines.append(f"- Availability Rate: `{_percent(summary.get('availability_rate'))}`")
    lines.append(
        f"- Contract Valid / Invalid: `{summary.get('contract_valid', 0)}` / "
        f"`{summary.get('contract_invalid', 0)}`"
    )
    lines.append(
        f"- Contract Valid Rate: `{_percent(summary.get('contract_valid_rate'))}`"
    )
    lines.append(f"- Unsafe Contracts: `{summary.get('unsafe_contract_count', 0)}`")
    lines.append(
        f"- BUY / HOLD / SELL: `{counts.get('buy', 0)}` / "
        f"`{counts.get('hold', 0)}` / `{counts.get('sell', 0)}`"
    )
    lines.append(f"- Average Agreement: `{_percent(summary.get('average_agreement'))}`")
    lines.append(
        f"- Would Pass Required Gate: "
        f"`{summary.get('would_pass_required_gate', 0)}`"
    )
    lines.append(
        f"- Would Be Blocked: `{summary.get('would_be_blocked', 0)}`"
    )
    lines.append(
        f"- Required Mode Readiness: "
        f"`{'eligible' if summary.get('required_mode_eligible') else 'not_ready'}`"
    )
    lines.append(
        f"- Observation Progress: `{summary.get('ensemble_observations', 0)}` / "
        f"`{summary.get('observation_target', 50)}`"
    )
    lines.append("- Safety: `Risk_Agent remains mandatory; direct execution forbidden`")
    lines.append("")

    lines.append(
        "| Symbol | Status | Signal | Agreement | Contract | Would Pass | "
        "Skills | Rejection Codes |"
    )
    lines.append("|---|---|---|---:|---|---|---:|---|")
    for row in rows:
        row = _legacy._dict(row)
        codes = row.get("rejection_codes") or []
        code_text = ", ".join(str(code) for code in codes) if codes else "-"
        contract = row.get("contract_valid")
        contract_text = "valid" if contract is True else "invalid" if contract is False else "-"
        pass_gate = row.get("would_pass_required_gate")
        pass_text = "yes" if pass_gate is True else "no" if pass_gate is False else "-"
        lines.append(
            f"| {row.get('symbol', '-')} | {row.get('status', '-')} | "
            f"{row.get('signal', '-')} | {_percent(row.get('agreement'))} | "
            f"{contract_text} | {pass_text} | "
            f"{row.get('selected_skill_count', 0)} | {code_text} |"
        )
    lines.append("")


def render_order_review_approval_ticket(
    lines: List[str],
    ticket_response: Dict[str, Any],
) -> None:
    if not ticket_response:
        return

    ticket = _legacy.unwrap_data(ticket_response) or {}
    if not isinstance(ticket, dict):
        return

    summary = _legacy._dict(ticket.get("summary"))
    ready = _legacy._list(ticket.get("ready_for_manual_approval"))
    no_action = _legacy._list(ticket.get("no_action_required"))
    blocked = _legacy._list(ticket.get("blocked"))
    if not summary and not ready and not no_action and not blocked:
        return

    ticket_status = ticket.get("ticket_status", "-")
    requires_attention = ticket.get(
        "requires_operator_attention",
        summary.get("requires_operator_attention", False),
    )

    lines.append("## Broker Order Review Approval Ticket")
    lines.append(f"- Mode: `{ticket.get('mode', '-')}`")
    lines.append(f"- Safety: `{ticket.get('safety', '-')}`")
    lines.append(f"- Ticket ID: `{ticket.get('ticket_id', '-')}`")
    lines.append(f"- Ticket Status: `{ticket_status}`")
    lines.append(f"- Requires Operator Attention: `{requires_attention}`")
    lines.append(f"- Approval Required: `{ticket.get('approval_required', False)}`")
    lines.append(f"- Execution Enabled: `{ticket.get('execution_enabled', False)}`")
    lines.append(
        f"- Manual Confirmation Phrase: "
        f"`{ticket.get('manual_confirmation_phrase', '-')}`"
    )
    lines.append(
        f"- Requested Symbols: "
        f"`{', '.join(ticket.get('requested_symbols') or []) or '-'}`"
    )
    lines.append(
        f"- Ready For Manual Approval: "
        f"`{summary.get('ready_for_manual_approval_count', len(ready))}`"
    )
    lines.append(
        f"- No Action Required: "
        f"`{summary.get('no_action_required_count', len(no_action))}`"
    )
    lines.append(f"- Blocked: `{summary.get('blocked_count', len(blocked))}`")
    lines.append(f"- Next Step: `{ticket.get('next_step', '-')}`")
    lines.append(
        f"- Orders Submitted By Ticket: "
        f"`{summary.get('orders_submitted', False)}`"
    )
    lines.append(
        f"- Orders Cancelled By Ticket: "
        f"`{summary.get('orders_cancelled', False)}`"
    )
    lines.append("")

    if ready:
        lines.append("### Ready For Manual Approval")
        lines.append(
            "| Symbol | Qty | Current Stop Order | Stop | TP | R/R | "
            "Approval Status | Proposed Actions |"
        )
        lines.append("|---|---:|---|---:|---:|---:|---|---:|")
        for row in ready:
            row = _legacy._dict(row)
            actions = _legacy._list(row.get("proposed_actions"))
            status = row.get("approval_status", "manual_approval_required")
            lines.append(
                f"| {row.get('symbol', '-')} | {row.get('position_qty', '-')} | "
                f"{row.get('current_stop_order_id', '-')} | "
                f"{row.get('stop_price', '-')} | "
                f"{row.get('take_profit_price', '-')} | "
                f"{row.get('reward_risk_ratio', '-')} | "
                f"{_legacy._status_icon(status)} `{status}` | {len(actions)} |"
            )
        lines.append("")

    if no_action:
        lines.append("### No Action Required")
        lines.append("| Symbol | Status | Reason | Recommended Next Step |")
        lines.append("|---|---|---|---|")
        for row in no_action:
            row = _legacy._dict(row)
            status = row.get("preview_status", "no_action_required")
            lines.append(
                f"| {row.get('symbol', '-')} | "
                f"{_legacy._status_icon(status)} `{status}` | "
                f"{row.get('reason', '-')} | "
                f"{row.get('recommended_next_step', '-')} |"
            )
        lines.append("")

    if blocked:
        lines.append("### Blocked Approval Ticket Items")
        lines.append("| Symbol | Status | Reason | Recommended Next Step |")
        lines.append("|---|---|---|---|")
        for row in blocked:
            row = _legacy._dict(row)
            status = row.get("preview_status", "-")
            lines.append(
                f"| {row.get('symbol', '-')} | "
                f"{_legacy._status_icon(status)} `{status}` | "
                f"{row.get('reason', '-')} | "
                f"{row.get('recommended_next_step', '-')} |"
            )
        lines.append("")

    if ticket_status == "ready_for_manual_approval":
        lines.append("### Manual Approval Safety")
        lines.append(
            "Ticket นี้เป็น read-only/manual-approval เท่านั้น "
            "ยังไม่ cancel/replace/submit order จริง "
            "ต้องมีขั้นตอนอนุมัติแยกก่อน execution"
        )
        lines.append("")
    elif ticket_status == "blocked":
        lines.append("### Operator Attention Required")
        lines.append(
            "Ticket นี้ยังมี blocker ต้องแก้ก่อน แล้วจึง refresh order review preview "
            "รอบนี้ยังไม่มีการ cancel/replace/submit order จริง"
        )
        lines.append("")
    elif ticket_status in {"no_action_required", "empty"}:
        lines.append("### No Operator Action Required")
        lines.append(
            "ไม่พบรายการที่ต้องอนุมัติหรือแก้ไขเพิ่มเติมใน Ticket รอบนี้ "
            "และไม่มีการ cancel/replace/submit order จริง"
        )
        lines.append("")


def _status_is_http_error(value: Any) -> bool:
    try:
        return int(value) >= 400
    except (TypeError, ValueError):
        return False


def _decode_error_body(body: Any) -> Optional[str]:
    if body in (None, ""):
        return None
    if isinstance(body, (dict, list)):
        return json.dumps(body, ensure_ascii=False, default=str)
    text = str(body)
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(decoded, dict):
        for key in ("detail", "message", "reason", "error"):
            value = decoded.get(key)
            if value:
                return str(value)
    return json.dumps(decoded, ensure_ascii=False, default=str)


def _manager_response_failure_message(raw: Dict[str, Any]) -> Optional[str]:
    response = raw.get("response")
    if not isinstance(response, dict):
        return None

    status = str(response.get("status") or "").lower()
    http_status = response.get("http_status")
    failed = status == "error" or _status_is_http_error(http_status)
    if not failed:
        return None

    body_message = _decode_error_body(response.get("body"))
    direct_error = response.get("error") or response.get("detail") or response.get("message")
    detail = body_message or direct_error or "Unknown manager workflow error"
    return (
        "Manager /discover-analyze-trade failed "
        f"with status={response.get('status', '-')} "
        f"http_status={response.get('http_status', '-')}: {detail}"
    )


def _write_failure_report(raw: Dict[str, Any], output_path: Path, message: str) -> None:
    lines = [
        "# รายงานระบบเทรดอัตโนมัติรายชั่วโมง",
        "",
        "## Manager Workflow Failure",
        f"- Generated at UTC: `{raw.get('generated_at', '-')}`",
        f"- Mode: `{raw.get('mode', '-')}`",
        f"- Broker Mode: `{raw.get('broker_mode', '-')}`",
        f"- Flow: `{raw.get('flow', '-')}`",
        f"- Failure: `{message}`",
        "",
        "### Request",
        "```json",
        json.dumps(raw.get("request") or {}, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "### Manager Response",
        "```json",
        json.dumps(raw.get("response") or {}, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "### Safety Note",
        "Broker diagnostics and snapshots may still be present, but the core "
        "discover/analyze/trade decision failed. The workflow must fail so "
        "GitHub Actions captures container diagnostics instead of publishing a "
        "green false-positive run.",
        "",
    ]
    output_path.write_text("\n".join(lines), encoding="utf-8")


_legacy.render_curator_signals = render_curator_signals
_legacy.render_order_review_approval_ticket = render_order_review_approval_ticket


def main() -> int:
    report_path = Path("reports/hourly-auto-trading-report.json")
    output_path = Path("reports/hourly-auto-trading-report.md")
    if not report_path.exists():
        print(f"missing {report_path}", file=sys.stderr)
        return 1

    raw = json.loads(report_path.read_text(encoding="utf-8"))
    failure_message = _manager_response_failure_message(raw)
    if failure_message:
        _write_failure_report(raw, output_path, failure_message)
        print(output_path.read_text(encoding="utf-8"))
        print(failure_message, file=sys.stderr)
        return 1

    return _legacy.main()


if __name__ == "__main__":
    raise SystemExit(main())

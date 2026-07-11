from typing import Any, Dict, List

try:
    from scripts.render_hourly_portfolio_report_legacy import *  # noqa: F401,F403
    import scripts.render_hourly_portfolio_report_legacy as _legacy
except ModuleNotFoundError:
    from render_hourly_portfolio_report_legacy import *  # type: ignore # noqa: F401,F403
    import render_hourly_portfolio_report_legacy as _legacy  # type: ignore


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


_legacy.render_order_review_approval_ticket = render_order_review_approval_ticket


if __name__ == "__main__":
    raise SystemExit(_legacy.main())

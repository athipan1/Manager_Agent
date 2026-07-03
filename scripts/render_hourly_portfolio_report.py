import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def th_verdict(value: Any) -> str:
    return {
        "strong_buy": "ซื้อแรง",
        "buy": "ซื้อ",
        "hold": "ถือ/รอดู",
        "sell": "ขาย",
        "strong_sell": "ขายแรง",
        "unknown": "ไม่ทราบผล",
    }.get(str(value).lower(), str(value))


def th_execution(value: Any) -> str:
    return {
        "submitted": "ส่งออเดอร์แล้ว",
        "rejected": "ไม่ส่งออเดอร์ / ถูกปฏิเสธ",
        "failed": "ส่งออเดอร์ไม่สำเร็จ",
        "not_attempted": "ยังไม่ส่งออเดอร์",
        "unknown": "ไม่ทราบสถานะ",
        "blocked": "ถูกบล็อกเพื่อความปลอดภัย",
    }.get(str(value).lower(), str(value))


def unwrap_data(value: Any) -> Any:
    if isinstance(value, dict) and "data" in value:
        return value.get("data")
    return value


def score(item: Dict[str, Any], key: str) -> Any:
    return (item.get("score_breakdown") or {}).get(key)


def _list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _row_value(row: Dict[str, Any], *keys: str, default: Any = "-") -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return default


def _execution_job_status(row: Dict[str, Any]) -> Any:
    job = _dict(row.get("execution_job"))
    return job.get("status") or job.get("job_status") or "-"


def approval_status(row: Dict[str, Any]) -> str:
    if row.get("approved") is True:
        return "approved"
    if row.get("approved") is False:
        return "rejected"
    return str(row.get("status") or "unknown")


def approval_reason(row: Dict[str, Any]) -> str:
    reasons = row.get("reasons") or row.get("errors") or row.get("warnings") or []
    if isinstance(reasons, list) and reasons:
        return "; ".join(str(item.get("code") or item.get("reason") or item) if isinstance(item, dict) else str(item) for item in reasons[:4])
    risk_response = row.get("risk_response") or row.get("risk") or {}
    nested = risk_response.get("reasons") or risk_response.get("errors") or risk_response.get("warnings") or []
    if isinstance(nested, list) and nested:
        return "; ".join(str(item.get("code") or item.get("reason") or item) if isinstance(item, dict) else str(item) for item in nested[:4])
    return str(row.get("reason") or risk_response.get("reason") or "-")


def _status_icon(status: Any) -> str:
    return {
        "bracket_protected": "✅",
        "tp_sl_protected": "✅",
        "stop_only": "⚠️",
        "unprotected": "🚨",
        "ready_for_manual_review": "🟡",
        "blocked_missing_stop_price": "⛔",
        "blocked_missing_reference_price": "⛔",
        "blocked_invalid_stop_direction": "⛔",
        "blocked_unprotected_position": "🚨",
        "no_action_required": "✅",
    }.get(str(status or "").lower(), "ℹ️")


def _sync_summary(database_sync: Dict[str, Any]) -> Dict[str, Any]:
    mismatch = _dict(database_sync.get("mismatch"))
    return _dict(mismatch.get("summary"))


def render_sync_preflight(lines: List[str], data: Dict[str, Any]) -> None:
    database_sync = _dict(data.get("database_sync"))
    database_sync_after_bucket_backfill = _dict(data.get("database_sync_after_bucket_backfill"))
    snapshot_capture = _dict(data.get("broker_snapshot_capture"))
    bucket_backfill_capture = _dict(data.get("bucket_backfill_capture"))
    snapshot_capture_status = data.get("broker_snapshot_capture_status")
    execution = _dict(data.get("execution"))
    summary = _sync_summary(database_sync)

    has_sync_data = bool(database_sync or snapshot_capture or snapshot_capture_status or bucket_backfill_capture)
    blocked_by_sync = "Database/Broker sync status" in str(execution.get("reason") or "")
    if not has_sync_data and not blocked_by_sync:
        return

    lines.append("## Database Sync Preflight")
    lines.append(f"- Broker Snapshot Capture Status: `{snapshot_capture_status or snapshot_capture.get('status', '-')}`")
    if bucket_backfill_capture:
        lines.append(f"- Bucket Backfill Capture Status: `{bucket_backfill_capture.get('status', '-')}`")
        bucket_hints = bucket_backfill_capture.get("bucket_hints") or {}
        if bucket_hints:
            lines.append(f"- Bucket Hints: `{json.dumps(bucket_hints, ensure_ascii=False, default=str)}`")
    if summary:
        lines.append(f"- Database Sync Status: `{summary.get('status', '-')}`")
        lines.append(f"- Severity: `{summary.get('severity', '-')}`")
        lines.append(f"- Recommended Action: `{summary.get('recommended_action', '-')}`")
    else:
        lines.append("- Database Sync Status: `-`")
    if execution.get("status") == "blocked":
        lines.append("- Safety Gate: `blocked`")
        lines.append(f"- Block Reason: {execution.get('reason', '-')}")
    lines.append("")

    for title, payload in [
        ("Broker Snapshot Capture", snapshot_capture),
        ("Bucket Backfill Capture", bucket_backfill_capture),
        ("Database Sync Diagnostics", database_sync),
        ("Database Sync After Bucket Backfill", database_sync_after_bucket_backfill),
    ]:
        if payload:
            lines.append(f"### {title}")
            lines.append("```json")
            lines.append(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
            lines.append("```")
            lines.append("")


def _curator_output(signal: Dict[str, Any]) -> Dict[str, Any]:
    execution = _dict(signal.get("execution"))
    return _dict(execution.get("output"))


def render_curator_signals(lines: List[str], data: Dict[str, Any]) -> None:
    curator_signals = _list(data.get("curator_signals"))
    if not curator_signals:
        return

    lines.append("## Curator Signals")
    lines.append(f"- Signals Returned: `{len(curator_signals)}`")
    lines.append("- Usage: `advisory_metadata_only`")
    lines.append("- Safety: `does_not_approve_size_or_submit_orders`")
    lines.append("")
    lines.append("| Symbol | Status | Skill | Signal | Confidence | Reason | Execution Status |")
    lines.append("|---|---|---|---|---:|---|---|")
    for row in curator_signals:
        row = _dict(row)
        output = _curator_output(row)
        execution = _dict(row.get("execution"))
        lines.append(
            f"| {_row_value(row, 'symbol')} | {_row_value(row, 'status')} | "
            f"{_row_value(row, 'skill_name', 'skill_id')} | {output.get('signal', '-')} | "
            f"{output.get('confidence', '-')} | {output.get('reason') or row.get('reason') or '-'} | "
            f"{execution.get('execution_status', '-')} |"
        )
    lines.append("")


def render_execution_details(lines: List[str], execution: Dict[str, Any]) -> None:
    if not execution:
        return

    created = _list(execution.get("created"))
    failed = _list(execution.get("failed"))
    failed_to_build = _list(execution.get("failed_to_build"))
    skipped = _list(execution.get("skipped_open_order_conflicts"))
    validation = _dict(execution.get("validation"))

    if not any([created, failed, failed_to_build, skipped, validation]):
        return

    lines.append("## Execution Details")
    lines.append(f"- Status: `{execution.get('status', '-')}`")
    lines.append(f"- Created Orders: `{len(created)}`")
    lines.append(f"- Failed Orders: `{len(failed)}`")
    lines.append(f"- Failed To Build: `{len(failed_to_build)}`")
    lines.append(f"- Skipped Open-Order Conflicts: `{len(skipped)}`")
    if validation:
        lines.append(f"- Validation Approved: `{validation.get('approved', '-')}`")
    lines.append("")

    if created:
        lines.append("### Created Orders")
        lines.append("| Symbol | Bucket | Quantity | Final Qty | Broker Order ID | Risk Approval ID | Status | Job Status |")
        lines.append("|---|---|---:|---:|---|---|---|---|")
        for row in created:
            row = _dict(row)
            order = _dict(row.get("order"))
            lines.append(
                f"| {_row_value(row, 'symbol')} | {_row_value(row, 'strategy_bucket')} | "
                f"{_row_value(row, 'quantity')} | {_row_value(row, 'final_quantity')} | "
                f"{_row_value(row, 'broker_order_id', default=order.get('broker_order_id') or '-')} | "
                f"{_row_value(row, 'risk_approval_id')} | {_row_value(row, 'status', default=order.get('status') or '-')} | {_execution_job_status(row)} |"
            )
        lines.append("")

    if skipped:
        lines.append("### Skipped Orders")
        lines.append("| Symbol | Quantity | Final Qty | Risk Approval ID | Reason |")
        lines.append("|---|---:|---:|---|---|")
        for row in skipped:
            row = _dict(row)
            lines.append(f"| {_row_value(row, 'symbol')} | {_row_value(row, 'quantity')} | {_row_value(row, 'final_quantity')} | {_row_value(row, 'risk_approval_id')} | {_row_value(row, 'reason')} |")
        lines.append("")

    if failed or failed_to_build:
        lines.append("### Failed Orders")
        lines.append("| Symbol | Quantity | Final Qty | Risk Approval ID | Reason |")
        lines.append("|---|---:|---:|---|---|")
        for row in failed + failed_to_build:
            row = _dict(row)
            lines.append(f"| {_row_value(row, 'symbol')} | {_row_value(row, 'quantity')} | {_row_value(row, 'final_quantity')} | {_row_value(row, 'risk_approval_id')} | {_row_value(row, 'reason')} |")
        lines.append("")

    if validation:
        lines.append("### Validation Details")
        lines.append("```json")
        lines.append(json.dumps(validation, ensure_ascii=False, indent=2, default=str))
        lines.append("```")
        lines.append("")


def render_protection_diagnostics(lines: List[str], diagnostics_response: Dict[str, Any]) -> None:
    if not diagnostics_response:
        return

    diagnostics = unwrap_data(diagnostics_response) or {}
    if not isinstance(diagnostics, dict):
        return

    summary = _dict(diagnostics.get("summary"))
    rows = _list(diagnostics.get("positions"))
    if not summary and not rows:
        return

    lines.append("## Broker Protection Diagnostics")
    lines.append(f"- Mode: `{diagnostics.get('mode', '-')}`")
    lines.append(f"- Safety: `{diagnostics.get('safety', '-')}`")
    lines.append(f"- Positions Checked: `{summary.get('position_count', len(rows))}`")
    lines.append(f"- Open Orders Checked: `{summary.get('open_order_count', '-')}`")
    lines.append(f"- Stop-only Positions: `{summary.get('stop_only_count', 0)}`")
    lines.append(f"- Needs Bracket Upgrade: `{summary.get('needs_bracket_upgrade_count', 0)}`")
    lines.append(f"- Unprotected Positions: `{summary.get('unprotected_position_count', 0)}`")
    lines.append(f"- Orders Submitted By Diagnostic: `{summary.get('orders_submitted', False)}`")
    lines.append("")

    if rows:
        lines.append("| Symbol | Status | Stop Loss | Take Profit | Bracket | Open Orders | Recommended Action |")
        lines.append("|---|---|---|---|---|---:|---|")
        for row in rows:
            row = _dict(row)
            status = row.get("protection_status", "-")
            lines.append(
                f"| {row.get('symbol', '-')} | {_status_icon(status)} `{status}` | "
                f"{row.get('has_protective_stop', '-')} | {row.get('has_take_profit', '-')} | "
                f"{row.get('has_bracket', '-')} | {row.get('open_order_count', '-')} | "
                f"{row.get('recommended_action', '-')} |"
            )
        lines.append("")

    if summary.get("needs_bracket_upgrade_count", 0) or summary.get("unprotected_position_count", 0):
        lines.append("### Protection Attention Required")
        lines.append("ตรวจพบ position ที่ยังไม่ครบ TP/SL แบบใหม่ รอบนี้เป็น diagnostic-only จึงยังไม่ cancel/replace order จริง")
        lines.append("")


def render_order_review_preview(lines: List[str], preview_response: Dict[str, Any]) -> None:
    if not preview_response:
        return

    preview = unwrap_data(preview_response) or {}
    if not isinstance(preview, dict):
        return

    summary = _dict(preview.get("summary"))
    plans = _list(preview.get("plans"))
    if not summary and not plans:
        return

    lines.append("## Broker Order Review Preview")
    lines.append(f"- Mode: `{preview.get('mode', '-')}`")
    lines.append(f"- Safety: `{preview.get('safety', '-')}`")
    lines.append(f"- Reward/Risk Ratio: `{preview.get('reward_risk_ratio', '-')}`")
    lines.append(f"- Candidates: `{summary.get('candidate_count', 0)}`")
    lines.append(f"- Ready For Manual Review: `{summary.get('ready_for_manual_review_count', 0)}`")
    lines.append(f"- Blocked: `{summary.get('blocked_count', 0)}`")
    lines.append(f"- No Action: `{summary.get('no_action_count', 0)}`")
    lines.append(f"- Orders Submitted By Preview: `{summary.get('orders_submitted', False)}`")
    lines.append(f"- Orders Cancelled By Preview: `{summary.get('orders_cancelled', False)}`")
    lines.append("")

    if plans:
        lines.append("| Symbol | Preview Status | Qty | Stop | TP | Next Step | Proposed Actions |")
        lines.append("|---|---|---:|---:|---:|---|---:|")
        for plan in plans:
            plan = _dict(plan)
            status = plan.get("preview_status", "-")
            actions = _list(plan.get("proposed_actions"))
            lines.append(
                f"| {plan.get('symbol', '-')} | {_status_icon(status)} `{status}` | "
                f"{plan.get('position_qty', '-')} | {plan.get('stop_price', '-')} | {plan.get('take_profit_price', '-')} | "
                f"{plan.get('recommended_next_step', '-')} | {len(actions)} |"
            )
        lines.append("")

    if summary.get("blocked_count", 0):
        lines.append("### Preview Attention Required")
        lines.append("บางรายการยังสร้างแผน bracket ไม่ได้ เพราะข้อมูล broker order ยังไม่ครบ เช่น stop_price/trigger_price รอบนี้เป็น preview-only จึงยังไม่ cancel/replace order จริง")
        lines.append("")


def render_portfolio_section(lines: List[str], data: Dict[str, Any]) -> None:
    allocation_plan = data.get("allocation_plan") or {}
    bucket_selection = data.get("bucket_selection") or {}
    selected_positions = data.get("selected_positions") or []
    risk_approvals = data.get("risk_approvals") or []
    execution_candidates = data.get("execution_candidates") or []
    execution = data.get("execution") or {}
    portfolio_summary = data.get("portfolio_summary") or {}

    render_sync_preflight(lines, data)

    lines.append("## Portfolio Summary")
    lines.append(f"- Mode: `{data.get('mode', 'portfolio_allocation')}`")
    lines.append(f"- Selected Positions: `{portfolio_summary.get('selected_positions', len(selected_positions))}`")
    lines.append(f"- Approved Positions: `{portfolio_summary.get('approved_positions', len([r for r in risk_approvals if approval_status(r) == 'approved']))}`")
    lines.append(f"- Execution Candidates: `{len(execution_candidates)}`")
    lines.append(f"- Curator Signals: `{portfolio_summary.get('curator_signals', len(_list(data.get('curator_signals'))))}`")
    if portfolio_summary.get("bucket_backfill_capture_status"):
        lines.append(f"- Bucket Backfill: `{portfolio_summary.get('bucket_backfill_capture_status')}`")
        lines.append(f"- Bucket Backfill Hints: `{portfolio_summary.get('bucket_backfill_hint_count', '-')}`")
    lines.append(f"- Execution: {th_execution(execution.get('status', 'unknown'))}")
    lines.append(f"- Execution Reason: {execution.get('reason', '-')}")
    lines.append("")

    if allocation_plan:
        policy_name = allocation_plan.get("policy_name") or allocation_plan.get("name") or "-"
        lines.append("## Allocation Plan")
        lines.append(f"- Policy: `{policy_name}`")
        buckets = allocation_plan.get("buckets") or allocation_plan.get("bucket_targets") or {}
        if isinstance(buckets, dict) and buckets:
            lines.append("| Bucket | Target Weight | Target Value |")
            lines.append("|---|---:|---:|")
            for bucket, info in buckets.items():
                info = info or {}
                lines.append(f"| {bucket} | {info.get('target_weight', info.get('weight', '-'))} | {info.get('target_value', '-')} |")
            lines.append("")

    if bucket_selection:
        lines.append("## Bucket Selection")
        lines.append("```json")
        lines.append(json.dumps(bucket_selection, ensure_ascii=False, indent=2, default=str))
        lines.append("```")
        lines.append("")

    lines.append("## Selected Positions")
    if not selected_positions:
        lines.append("No selected portfolio positions returned by Manager_Agent.")
    else:
        lines.append("| # | Symbol | Bucket | Target Weight | Target Value | Score |")
        lines.append("|---:|---|---|---:|---:|---:|")
        for index, item in enumerate(selected_positions, start=1):
            lines.append(
                f"| {index} | {item.get('symbol', '-')} | {item.get('strategy_bucket') or item.get('bucket', '-')} | "
                f"{item.get('target_weight', '-')} | {item.get('target_value', '-')} | {score(item, 'final_opportunity_score') or item.get('final_score', '-')} |"
            )
    lines.append("")

    render_curator_signals(lines, data)

    lines.append("## Risk Approvals")
    if not risk_approvals:
        lines.append("No risk approvals returned.")
    else:
        lines.append("| Symbol | Bucket | Status | Final Qty | Risk Approval ID | Reason |")
        lines.append("|---|---|---|---:|---|---|")
        for row in risk_approvals:
            lines.append(
                f"| {row.get('symbol', '-')} | {row.get('strategy_bucket') or row.get('bucket', '-')} | "
                f"{approval_status(row)} | {row.get('final_quantity') or row.get('approved_quantity') or '-'} | "
                f"{row.get('risk_approval_id') or row.get('approval_id') or '-'} | {approval_reason(row)} |"
            )
    lines.append("")

    lines.append("## Execution Candidates")
    if not execution_candidates:
        lines.append("No execution candidates were submitted.")
    else:
        lines.append("| Symbol | Bucket | Quantity | Risk Approval ID | Status |")
        lines.append("|---|---|---:|---|---|")
        for row in execution_candidates:
            lines.append(
                f"| {row.get('symbol', '-')} | {row.get('strategy_bucket') or row.get('bucket', '-')} | "
                f"{row.get('quantity') or row.get('final_quantity') or '-'} | {row.get('risk_approval_id') or '-'} | {row.get('status') or '-'} |"
            )
    lines.append("")

    render_execution_details(lines, execution)


def render_ranked_candidates(lines: List[str], data: Dict[str, Any]) -> None:
    ranked = _list(data.get("ranked_candidates"))
    if not ranked:
        return
    lines.append("## Ranked Candidates")
    lines.append("| Rank | Symbol | Verdict | Bucket | Final Score | Scanner | Fundamental | Technical |")
    lines.append("|---:|---|---|---|---:|---:|---:|---:|")
    for index, item in enumerate(ranked[:15], start=1):
        breakdown = item.get("score_breakdown") or {}
        lines.append(
            f"| {index} | {item.get('symbol', '-')} | {th_verdict(item.get('final_verdict', '-'))} | "
            f"{item.get('strategy_bucket') or breakdown.get('strategy_bucket') or '-'} | "
            f"{breakdown.get('final_opportunity_score') or item.get('final_score', '-')} | "
            f"{breakdown.get('scanner_score', '-')} | {breakdown.get('fundamental_score', '-')} | {breakdown.get('technical_score', '-')} |"
        )
    lines.append("")


def render_broker_snapshot(lines: List[str], snapshot: Dict[str, Any]) -> None:
    if not snapshot:
        return
    account = unwrap_data(snapshot.get("account")) or {}
    orders = unwrap_data(snapshot.get("orders")) or []
    positions = unwrap_data(snapshot.get("positions")) or []
    lines.append("## Broker Snapshot")
    if isinstance(account, dict):
        lines.append(f"- Account Status: `{account.get('status', '-')}`")
        lines.append(f"- Equity: `{account.get('equity', '-')}`")
        lines.append(f"- Cash: `{account.get('cash', '-')}`")
        lines.append(f"- Buying Power: `{account.get('buying_power', '-')}`")
    lines.append(f"- Open Orders: `{len(orders) if isinstance(orders, list) else '-'}`")
    lines.append(f"- Positions: `{len(positions) if isinstance(positions, list) else '-'}`")
    lines.append("")
    lines.append("### Raw Broker Snapshot")
    lines.append("```json")
    lines.append(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str))
    lines.append("```")


def render_dashboard(lines: List[str], dashboard: Dict[str, Any]) -> None:
    if not dashboard:
        return
    data = unwrap_data(dashboard) or {}
    if not isinstance(data, dict):
        return
    lines.append("## Dashboard Snapshot")
    lines.append(f"- ปัญหาระบบ: `{len(data.get('alerts') or [])}`")
    account = data.get("account") or {}
    if account:
        lines.append(f"- ยอดเงินคงเหลือ: `{account.get('cash_balance', account.get('cash', '-'))}`")
    lines.append(f"- หุ้นที่ถืออยู่: `{len(data.get('positions') or [])}`")
    lines.append(f"- ออเดอร์ที่เปิดอยู่: `{len(data.get('open_orders') or [])}`")
    lines.append(f"- ประวัติการซื้อขาย: `{len(data.get('trade_history') or [])}`")
    lines.append("")
    alerts = data.get("alerts") or []
    if alerts:
        lines.append("### ปัญหา / Alerts")
        lines.append("| ระดับ | ประเภท | ข้อความ | เวลา |")
        lines.append("|---|---|---|---|")
        for alert in alerts:
            lines.append(f"| {alert.get('severity', '-')} | {alert.get('type', '-')} | {alert.get('message', '-')} | {alert.get('timestamp', '-')} |")
        lines.append("")


def main() -> int:
    report_path = Path("reports/hourly-auto-trading-report.json")
    output_path = Path("reports/hourly-auto-trading-report.md")
    if not report_path.exists():
        print(f"missing {report_path}", file=sys.stderr)
        return 1

    raw = json.loads(report_path.read_text())
    response = unwrap_data(raw.get("response") or {}) or {}
    if isinstance(response, dict) and "data" in response:
        response = response.get("data") or {}
    lines: List[str] = []
    lines.append("# รายงานระบบเทรดอัตโนมัติรายชั่วโมง")
    lines.append("")
    lines.append(f"Generated at UTC: `{raw.get('generated_at', '-')}`")
    lines.append(f"Mode: `{raw.get('mode', '-')}`")
    lines.append(f"Broker Mode: `{raw.get('broker_mode', '-')}`")
    lines.append(f"Flow: `{raw.get('flow', '-')}`")
    lines.append("")
    render_dashboard(lines, raw.get("dashboard_data") or {})
    lines.append("## Request")
    lines.append("```json")
    lines.append(json.dumps(raw.get("request") or {}, ensure_ascii=False, indent=2, default=str))
    lines.append("```")
    lines.append("")
    if isinstance(response, dict):
        render_portfolio_section(lines, response)
        render_ranked_candidates(lines, response)
    render_protection_diagnostics(lines, raw.get("protection_diagnostics") or {})
    render_order_review_preview(lines, raw.get("order_review_preview") or {})
    render_broker_snapshot(lines, raw.get("broker_snapshot") or {})
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(output_path.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

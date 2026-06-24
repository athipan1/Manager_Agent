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
    }.get(str(value).lower(), str(value))


def unwrap_data(value: Any) -> Any:
    if isinstance(value, dict) and "data" in value:
        return value.get("data")
    return value


def score(item: Dict[str, Any], key: str) -> Any:
    return (item.get("score_breakdown") or {}).get(key)


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


def render_portfolio_section(lines: List[str], data: Dict[str, Any]) -> None:
    allocation_plan = data.get("allocation_plan") or {}
    bucket_selection = data.get("bucket_selection") or {}
    selected_positions = data.get("selected_positions") or []
    risk_approvals = data.get("risk_approvals") or []
    execution_candidates = data.get("execution_candidates") or []
    execution = data.get("execution") or {}
    portfolio_summary = data.get("portfolio_summary") or {}

    lines.append("## Portfolio Summary")
    lines.append(f"- Mode: `{data.get('mode', 'portfolio_allocation')}`")
    lines.append(f"- Selected Positions: `{portfolio_summary.get('selected_positions', len(selected_positions))}`")
    lines.append(f"- Approved Positions: `{portfolio_summary.get('approved_positions', len([r for r in risk_approvals if approval_status(r) == 'approved']))}`")
    lines.append(f"- Execution Candidates: `{len(execution_candidates)}`")
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
                f"{row.get('quantity') or row.get('final_quantity') or '-'} | {row.get('risk_approval_id') or '-'} | {row.get('status', '-')} |"
            )
    lines.append("")


def render_ranked(lines: List[str], ranked: List[Dict[str, Any]]) -> None:
    lines.append("## Ranked Candidates")
    if not ranked:
        lines.append("No ranked candidates returned by Manager_Agent.")
    else:
        lines.append("| Rank | Symbol | Verdict | Bucket | Final Score | Scanner | Fundamental | Technical |")
        lines.append("|---:|---|---|---|---:|---:|---:|---:|")
        for item in ranked:
            scores = item.get("score_breakdown") or {}
            lines.append(
                f"| {item.get('rank')} | {item.get('symbol')} | {th_verdict(item.get('final_verdict'))} | "
                f"{item.get('strategy_bucket') or item.get('bucket', '-')} | {scores.get('final_opportunity_score')} | "
                f"{scores.get('scanner_score')} | {scores.get('fundamental_score')} | {scores.get('technical_score')} |"
            )
    lines.append("")


def main() -> int:
    report_path = Path("reports/hourly-auto-trading-report.json")
    report = json.loads(report_path.read_text())
    response = report.get("response") or {}
    data = response.get("data") if isinstance(response, dict) else {}
    data = data or {}
    snapshot = report.get("broker_snapshot") or {}
    dashboard = report.get("dashboard_data") or {}
    dashboard_data = dashboard.get("data") if isinstance(dashboard, dict) else {}

    lines: List[str] = []
    lines.append("# รายงานระบบเทรดอัตโนมัติรายชั่วโมง")
    lines.append("")
    lines.append(f"Generated at UTC: `{report.get('generated_at')}`")
    lines.append(f"Mode: `{report.get('mode')}`")
    lines.append(f"Broker Mode: `{report.get('broker_mode')}`")
    lines.append(f"Flow: `{report.get('flow')}`")
    lines.append("")

    if isinstance(dashboard_data, dict):
        summary = dashboard_data.get("summary") or {}
        balance = dashboard_data.get("balance") or {}
        lines.append("## Dashboard Snapshot")
        lines.append(f"- ปัญหาระบบ: `{summary.get('problem_count', 0)}`")
        lines.append(f"- ยอดเงินคงเหลือ: `{balance.get('cash_balance') or balance.get('cash') or balance.get('buying_power') or '-'}`")
        lines.append(f"- หุ้นที่ถืออยู่: `{summary.get('position_count', 0)}`")
        lines.append(f"- ออเดอร์ที่เปิดอยู่: `{summary.get('open_order_count', 0)}`")
        lines.append(f"- ประวัติการซื้อขาย: `{summary.get('trade_count', 0)}`")
        lines.append("")
        problems = dashboard_data.get("problems") or []
        if problems:
            lines.append("### ปัญหา / Alerts")
            lines.append("| ระดับ | ประเภท | ข้อความ | เวลา |")
            lines.append("|---|---|---|---|")
            for item in problems[:10]:
                lines.append(f"| {item.get('severity', '-')} | {item.get('alert_type', '-')} | {item.get('message', '-')} | {item.get('created_at', '-')} |")
            lines.append("")

    lines.append("## Request")
    lines.append("```json")
    lines.append(json.dumps(report.get("request"), ensure_ascii=False, indent=2))
    lines.append("```")
    lines.append("")

    if response.get("status") == "error":
        lines.append("## Error")
        lines.append("```json")
        lines.append(json.dumps(response, ensure_ascii=False, indent=2))
        lines.append("```")
    elif data.get("mode") == "portfolio_allocation" or data.get("selected_positions") is not None:
        render_portfolio_section(lines, data)
        render_ranked(lines, data.get("ranked_candidates") or [])
    else:
        winner = data.get("winner") or {}
        execution = data.get("execution") or {}
        trade_decision = data.get("trade_decision")
        lines.append("## Winner")
        lines.append(f"- Symbol: `{winner.get('symbol', '-')}`")
        lines.append(f"- Verdict: {th_verdict(winner.get('final_verdict', 'unknown'))}")
        lines.append(f"- Final Opportunity Score: `{score(winner, 'final_opportunity_score')}`")
        lines.append(f"- Execution: {th_execution(execution.get('status', 'unknown'))}")
        lines.append(f"- Execution Reason: {execution.get('reason', '-')}")
        lines.append("")
        render_ranked(lines, data.get("ranked_candidates") or [])
        lines.append("## Trade Decision")
        lines.append("```json")
        lines.append(json.dumps(trade_decision, ensure_ascii=False, indent=2, default=str))
        lines.append("```")

    account = unwrap_data(snapshot.get("account")) or {}
    orders = unwrap_data(snapshot.get("orders")) or []
    positions = unwrap_data(snapshot.get("positions")) or []
    lines.append("")
    lines.append("## Broker Snapshot")
    lines.append(f"- Account Status: `{account.get('status', '-') if isinstance(account, dict) else '-'}`")
    lines.append(f"- Equity: `{account.get('equity', '-') if isinstance(account, dict) else '-'}`")
    lines.append(f"- Cash: `{account.get('cash', '-') if isinstance(account, dict) else '-'}`")
    lines.append(f"- Buying Power: `{account.get('buying_power', '-') if isinstance(account, dict) else '-'}`")
    lines.append(f"- Open Orders: `{len(orders) if isinstance(orders, list) else '-'}`")
    lines.append(f"- Positions: `{len(positions) if isinstance(positions, list) else '-'}`")
    lines.append("")
    lines.append("### Raw Broker Snapshot")
    lines.append("```json")
    lines.append(json.dumps(snapshot, ensure_ascii=False, indent=2, default=str))
    lines.append("```")

    Path("reports/dashboard-data.json").write_text(json.dumps(dashboard, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    Path("reports/hourly-auto-trading-report.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))
    return 1 if response.get("status") == "error" else 0


if __name__ == "__main__":
    sys.exit(main())

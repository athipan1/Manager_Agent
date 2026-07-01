from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def text(value: Any, default: str = "-") -> str:
    if value is None or value == "":
        return default
    return str(value).replace("|", "/")


def first_reason(row: Dict[str, Any]) -> str:
    plan = row.get("profit_plan") or {}
    actions = plan.get("actions") or []
    if actions and isinstance(actions[0], dict):
        return text(actions[0].get("reason"))
    return text(plan.get("reason"))


def final_decision(row: Dict[str, Any]) -> str:
    plan = row.get("profit_plan") or {}
    action = str(plan.get("primary_action") or "hold").lower()
    risk_status = str(row.get("risk_status") or "not_submitted").lower()
    preview_status = str(row.get("execution_preview_status") or "not_submitted").lower()

    if risk_status != "approved":
        return "BLOCKED_BY_RISK"
    if preview_status == "blocked":
        return "BLOCKED_BY_PREVIEW"
    if action == "hold":
        return "HOLD"
    if action == "move_stop":
        return "REVIEW_STOP_CHANGE"
    if action == "partial_exit":
        return "REVIEW_PARTIAL_EXIT"
    if action == "exit_all":
        return "MANUAL_REVIEW_REQUIRED"
    return "REVIEW_REQUIRED"


def render_final_report(report: Dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    safety = report.get("safety") or {}
    rows: List[Dict[str, Any]] = report.get("reviewed_positions") or []
    bucket = report.get("bucket", "-")
    config = report.get("config") or {}

    lines = [
        f"# Final Bucket Review Report — {text(bucket)}",
        "",
        f"Generated at UTC: `{text(report.get('generated_at'))}`",
        f"Review title: `{text(config.get('review_title'))}`",
        f"Frequency: `{text(config.get('frequency'))}`",
        f"Mode: `{text(report.get('mode'))}`",
        "",
        "## Summary",
        f"- Positions seen: `{summary.get('positions_seen', 0)}`",
        f"- Reviewed positions: `{summary.get('reviewed_positions', 0)}`",
        f"- Database bucket hints applied: `{summary.get('database_bucket_hints_applied', 0)}`",
        f"- Fallback bucket hints applied: `{summary.get('bucket_hints_applied', 0)}`",
        f"- Profit Agent used: `{summary.get('profit_agent_used', 0)}`",
        f"- Risk submissions: `{summary.get('risk_submissions', 0)}`",
        f"- Risk approved: `{summary.get('risk_approved', 0)}`",
        f"- Risk rejected: `{summary.get('risk_rejected', 0)}`",
        f"- Preview submissions: `{summary.get('execution_preview_submissions', 0)}`",
        f"- Preview ready: `{summary.get('execution_preview_ready', 0)}`",
        f"- Preview blocked: `{summary.get('execution_preview_blocked', 0)}`",
        "",
        "## Safety",
        f"- Advisory only: `{str(safety.get('advisory_only', True)).lower()}`",
        f"- Any submitted broker action: `{str(safety.get('orders_submitted', False)).lower()}`",
        "",
        "## Final Decisions",
    ]

    if not rows:
        lines.append("No reviewed positions matched this bucket.")
    else:
        lines.append("| Symbol | Bucket | Profit Action | Risk Status | Preview Status | Final Decision | Reason |")
        lines.append("|---|---|---|---|---|---|---|")
        for row in rows:
            plan = row.get("profit_plan") or {}
            lines.append(
                "| "
                + " | ".join(
                    [
                        text(row.get("symbol")),
                        text(row.get("bucket")),
                        text(plan.get("primary_action")),
                        text(row.get("risk_status")),
                        text(row.get("execution_preview_status")),
                        final_decision(row),
                        first_reason(row),
                    ]
                )
                + " |"
            )

    lines.extend([
        "",
        "## Bucket Distribution",
        "```json",
        json.dumps(report.get("bucket_distribution") or {}, ensure_ascii=False, indent=2, default=str),
        "```",
        "",
        "## Compact JSON Summary",
        "```json",
        json.dumps({"summary": summary, "safety": safety}, ensure_ascii=False, indent=2, default=str),
        "```",
    ])
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a consolidated final bucket review report.")
    parser.add_argument("--input-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = json.loads(args.input_json.read_text(encoding="utf-8"))
    output = render_final_report(report)
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(output, encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

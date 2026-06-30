from __future__ import annotations

import argparse
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List


def request_json(base_url: str, path: str, payload: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    req = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
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


def build_gate_payload(row: Dict[str, Any]) -> Dict[str, Any]:
    profit_request = row.get("profit_request") or {}
    position = profit_request.get("position") or {}
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
        "profit_plan": row.get("profit_plan") or {},
        "trading_mode": "PAPER",
        "require_manual_exit_all": True,
    }


def apply_risk_gate(report: Dict[str, Any], risk_url: str) -> Dict[str, Any]:
    reviewed: List[Dict[str, Any]] = report.get("reviewed_positions") or []
    submitted = 0
    accepted = 0
    rejected = 0
    for row in reviewed:
        payload = build_gate_payload(row)
        result = request_json(risk_url, "/risk/profit-plan-gate", payload)
        data = unwrap(result) or {}
        row["risk_request"] = payload
        row["risk_result"] = data
        row["risk_status"] = "approved" if data.get("approved") is True else data.get("status") or "error"
        submitted += 1
        if row["risk_status"] == "approved":
            accepted += 1
        elif row["risk_status"] == "rejected":
            rejected += 1
    summary = report.setdefault("summary", {})
    summary["risk_submissions"] = submitted
    summary["risk_approved"] = accepted
    summary["risk_rejected"] = rejected
    safety = report.setdefault("safety", {})
    safety["risk_agent_submitted"] = submitted > 0
    return report


def render_compact_summary(report: Dict[str, Any]) -> str:
    summary = report.get("summary") or {}
    lines = [
        "# Profit Risk Gate Report",
        "",
        f"Bucket: `{report.get('bucket', '-')}`",
        f"Reviewed Positions: `{summary.get('reviewed_positions', 0)}`",
        f"Risk Submissions: `{summary.get('risk_submissions', 0)}`",
        f"Risk Approved: `{summary.get('risk_approved', 0)}`",
        f"Risk Rejected: `{summary.get('risk_rejected', 0)}`",
        "",
        "| Symbol | Profit Action | Risk Status |",
        "|---|---|---|",
    ]
    for row in report.get("reviewed_positions") or []:
        plan = row.get("profit_plan") or {}
        lines.append(f"| {row.get('symbol', '-')} | {plan.get('primary_action', '-')} | {row.get('risk_status', '-')} |")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply Risk_Agent profit-plan gate to an existing bucket review report.")
    parser.add_argument("--risk-url", default=os.getenv("RISK_AGENT_URL", "http://localhost:8007"))
    parser.add_argument("--input-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = json.loads(args.input_json.read_text(encoding="utf-8"))
    updated = apply_risk_gate(report, args.risk_url)
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(updated, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    if args.output_md:
        args.output_md.write_text(render_compact_summary(updated), encoding="utf-8")
    print(render_compact_summary(updated))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

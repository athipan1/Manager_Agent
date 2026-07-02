from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def find_unassigned_positions(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    positions = report.get("positions") or report.get("all_positions") or report.get("raw_positions") or []
    reviewed_symbols = {str(item.get("symbol") or "").upper() for item in report.get("reviewed_positions") or []}
    output: List[Dict[str, Any]] = []
    for item in positions:
        if not isinstance(item, dict):
            continue
        symbol = str(item.get("symbol") or "").upper()
        bucket = str(item.get("bucket") or item.get("strategy_bucket") or "unassigned").lower()
        if symbol and bucket == "unassigned" and symbol not in reviewed_symbols:
            output.append({
                "symbol": symbol,
                "bucket": bucket,
                "quantity": item.get("quantity"),
                "current_price": item.get("current_price"),
                "note": "manual bucket review required",
            })
    distribution = report.get("bucket_distribution") or {}
    if not output and int(distribution.get("unassigned") or 0) > 0:
        output.append({"symbol": "UNKNOWN", "bucket": "unassigned", "note": "bucket distribution reports unassigned positions"})
    return output


def render_markdown(report: Dict[str, Any], unassigned: List[Dict[str, Any]]) -> str:
    bucket = report.get("bucket") or "unknown"
    lines = [
        f"# Unassigned Bucket Report — {bucket}",
        "",
        f"Generated from review: `{report.get('generated_at', 'unknown')}`",
        "",
        f"Unassigned positions found: `{len(unassigned)}`",
        "",
    ]
    if not unassigned:
        lines.extend(["No unassigned positions were detected.", ""])
        return "\n".join(lines)
    lines.extend([
        "## Positions requiring manual bucket review",
        "| Symbol | Bucket | Quantity | Current Price | Note |",
        "|---|---|---:|---:|---|",
    ])
    for item in unassigned:
        lines.append(
            "| {symbol} | {bucket} | {quantity} | {current_price} | {note} |".format(
                symbol=item.get("symbol") or "-",
                bucket=item.get("bucket") or "-",
                quantity=item.get("quantity") if item.get("quantity") is not None else "-",
                current_price=item.get("current_price") if item.get("current_price") is not None else "-",
                note=item.get("note") or "-",
            )
        )
    lines.extend([
        "",
        "## Required action",
        "Choose and seed a strategy bucket manually before using the position in bucket-level review decisions.",
        "",
    ])
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render a report for positions that still need manual bucket assignment.")
    parser.add_argument("--input-json", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-md", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = json.loads(args.input_json.read_text(encoding="utf-8"))
    unassigned = find_unassigned_positions(report)
    payload = {"unassigned_count": len(unassigned), "unassigned_positions": unassigned}
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    args.output_md.write_text(render_markdown(report, unassigned), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

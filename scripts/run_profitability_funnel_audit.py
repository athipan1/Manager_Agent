from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.build_profitability_funnel import (
        build_profitability_funnel,
        render_markdown,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from build_profitability_funnel import (
        build_profitability_funnel,
        render_markdown,
    )


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _read_json(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _extract_cycle_id(upstream: dict[str, Any]) -> str | None:
    for key in ("portfolioCycleId", "portfolio_cycle_id", "cycle_id"):
        value = upstream.get(key)
        if value:
            return str(value)
    runtime = _dict(upstream.get("runtime"))
    for key in ("portfolioCycleId", "portfolio_cycle_id", "cycle_id"):
        value = runtime.get(key)
        if value:
            return str(value)
    return None


def build_upstream_failure_funnel(
    *,
    upstream_report: dict[str, Any] | None,
    source_run_id: str | None,
    source_run_conclusion: str | None,
) -> dict[str, Any]:
    upstream = upstream_report or {}
    conclusion = str(source_run_conclusion or "unknown").lower()
    cycle_status = str(
        upstream.get("cycleStatus")
        or upstream.get("cycle_status")
        or upstream.get("status")
        or "unavailable"
    )
    reason_codes = ["scanner_discovery_artifact_missing"]
    if conclusion not in {"success", "unknown", ""}:
        reason_codes.append(f"hourly_workflow_{conclusion}")
    if cycle_status and cycle_status not in {"success", "unavailable"}:
        reason_codes.append(f"hourly_cycle_{cycle_status.lower()}")

    bottleneck = {
        "stage": "upstream_runtime",
        "severity": "high",
        "observed": "scanner_not_reached",
        "target": "hourly_runtime_reaches_scanner_preselection",
        "lost_count": 0,
        "reason_codes": sorted(set(reason_codes)),
        "recommended_action": (
            "Repair the earliest failing Hourly runtime phase before tuning Scanner, "
            "Backtest, Investability, Risk, or Execution thresholds."
        ),
    }
    return {
        "schema_version": "profitability-funnel.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "portfolio_cycle_id": _extract_cycle_id(upstream),
        "source_status": "upstream_failed_before_scanner",
        "source_run_id": source_run_id,
        "source_run_conclusion": conclusion,
        "stages": [
            {"name": "hourly_runtime", "count": 1},
            {"name": "scanner_preselection_reached", "count": 0},
        ],
        "health": {
            "scanner_not_run": True,
            "scanner_success_rate": 0.0,
            "scanner_provider_pressure_detected": False,
            "scanner_error_categories": {},
            "data_quality_gate_decision": None,
            "quarantine_count": 0,
            "investability_rejection_codes": {},
            "backtest_symbols": [],
        },
        "primary_bottleneck": bottleneck,
        "active_bottlenecks": [bottleneck],
        "upstream": {
            "hourly_cycle_status": cycle_status,
            "discovery_artifact_present": False,
        },
        "safety": {
            "risk_thresholds_relaxed": False,
            "investability_thresholds_relaxed": False,
            "purpose": "diagnostic_only",
        },
    }


def render_upstream_markdown(funnel: dict[str, Any]) -> str:
    primary = _dict(funnel.get("primary_bottleneck"))
    upstream = _dict(funnel.get("upstream"))
    return "\n".join(
        [
            "# Hourly Profitability Funnel Audit",
            "",
            f"Schema: `{funnel.get('schema_version')}`",
            f"Source run: `{funnel.get('source_run_id') or '-'}`",
            f"Source conclusion: `{funnel.get('source_run_conclusion') or 'unknown'}`",
            "",
            "## Funnel unavailable",
            "",
            "Scanner preselection was not reached, so candidate conversion metrics would be misleading.",
            f"- Hourly cycle status: `{upstream.get('hourly_cycle_status') or 'unavailable'}`",
            f"- Primary bottleneck: `{primary.get('stage') or 'upstream_runtime'}`",
            f"- Action: {primary.get('recommended_action')}",
            "",
            "Safety: this report is diagnostic only; it does not relax Risk or Investability thresholds.",
            "",
        ]
    )


def run_audit(
    *,
    discovery_path: Path,
    upstream_report_path: Path | None,
    output_path: Path,
    markdown_path: Path | None,
    source_run_id: str | None,
    source_run_conclusion: str | None,
) -> dict[str, Any]:
    if discovery_path.exists():
        funnel = build_profitability_funnel(_read_json(discovery_path))
        funnel["source_run_id"] = source_run_id
        funnel["source_run_conclusion"] = source_run_conclusion
        markdown = render_markdown(funnel)
    else:
        funnel = build_upstream_failure_funnel(
            upstream_report=_read_json(upstream_report_path),
            source_run_id=source_run_id,
            source_run_conclusion=source_run_conclusion,
        )
        markdown = render_upstream_markdown(funnel)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(funnel, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(markdown, encoding="utf-8")
    return funnel


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a profitability funnel or an upstream-runtime diagnostic."
    )
    parser.add_argument("--discovery", type=Path, required=True)
    parser.add_argument("--upstream-report", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--source-run-id")
    parser.add_argument("--source-run-conclusion")
    args = parser.parse_args()

    funnel = run_audit(
        discovery_path=args.discovery,
        upstream_report_path=args.upstream_report,
        output_path=args.output,
        markdown_path=args.markdown,
        source_run_id=args.source_run_id,
        source_run_conclusion=args.source_run_conclusion,
    )
    print(
        json.dumps(
            {
                "source_status": funnel.get("source_status"),
                "primary_bottleneck": _dict(funnel.get("primary_bottleneck")).get(
                    "stage"
                ),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

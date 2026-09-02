from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 4)


def _aggregate_codes(rows: list[Any], field: str) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        if not isinstance(row, dict):
            continue
        for code in _list(row.get(field)):
            text = str(code or "").strip()
            if text:
                counter[text] += 1
    return dict(sorted(counter.items()))


def _evaluation_reason_counts(gate: dict[str, Any]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in _list(gate.get("evaluations")):
        if not isinstance(row, dict) or row.get("allowed") is True:
            continue
        code = str(row.get("reason_code") or "").strip()
        if code:
            counter[code] += 1
    if not counter:
        for code in _list(gate.get("review_reason_codes")):
            text = str(code or "").strip()
            if text:
                counter[text] += 1
    return dict(sorted(counter.items()))


def _top_reason_counts(*groups: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for group in groups:
        for code, raw_count in group.items():
            text = str(code or "").strip()
            if not text:
                continue
            count = _int(raw_count)
            if count > 0:
                counter[text] += count
    return [
        {"code": code, "count": count}
        for code, count in counter.most_common(max(1, limit))
    ]


def _active_bottlenecks(
    *,
    attempted: int,
    analyzed: int,
    quality_input: int,
    data_quality_passed: int,
    opportunity_passed: int,
    research_candidates: int,
    deep_analysis: int,
    classified: int,
    selected_before_investability: int,
    selected_after_investability: int,
    exposure_allowed: int,
    backtest_symbols: int,
    scanner_metadata: dict[str, Any],
    bucket_summary: dict[str, Any],
    investability_gate: dict[str, Any],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    scanner_success = _ratio(analyzed, attempted)
    data_quality_gate = _dict(scanner_metadata.get("scanner_data_quality_gate"))
    opportunity_gate = _dict(scanner_metadata.get("scanner_opportunity_gate"))

    if attempted > 0 and scanner_success < 0.8:
        issues.append(
            {
                "stage": "scanner_provider_coverage",
                "severity": "high" if scanner_success < 0.5 else "medium",
                "observed": scanner_success,
                "target": 0.8,
                "lost_count": max(0, attempted - analyzed),
                "reason_codes": _dict(scanner_metadata.get("error_categories")),
                "recommended_action": (
                    "Improve financial-provider coverage, caching/fallback and rate-limit handling before relaxing trading gates."
                ),
            }
        )

    if quality_input > 0 and data_quality_passed < quality_input:
        issues.append(
            {
                "stage": "scanner_analysis_data_quality_gate",
                "severity": "medium",
                "observed": _ratio(data_quality_passed, quality_input),
                "target": 1.0,
                "lost_count": max(0, quality_input - data_quality_passed),
                "reason_codes": _evaluation_reason_counts(data_quality_gate),
                "coverage_scope_counts": _dict(data_quality_gate.get("coverage_scope_counts")),
                "recommended_action": (
                    "Repair the missing analysis-ready evidence named by the gate; do not lower the 0.80 threshold."
                ),
            }
        )

    if data_quality_passed > opportunity_passed:
        controlled_shadow = research_candidates > 0
        issues.append(
            {
                "stage": "scanner_production_opportunity_gate",
                "severity": "informational" if controlled_shadow else "medium",
                "observed": _ratio(opportunity_passed, data_quality_passed),
                "target": "production only when live execution evidence is valid",
                "lost_count": max(0, data_quality_passed - opportunity_passed),
                "research_candidate_count": research_candidates,
                "reason_codes": _evaluation_reason_counts(opportunity_gate),
                "recommended_action": (
                    "Keep Production fail-closed. Off-session or non-production candidates should continue only through the broker-isolated Shadow lane."
                ),
            }
        )

    if deep_analysis > 0 and classified == 0:
        issues.append(
            {
                "stage": "strategy_classification",
                "severity": "high",
                "observed": 0.0,
                "target": "at_least_one_classified_candidate_when_evidence_supports_it",
                "lost_count": deep_analysis,
                "reason_codes": ["no_classified_evidence_eligible_candidate"],
                "recommended_action": (
                    "Review bucket classifier evidence rules; do not lower confidence thresholds without evidence."
                ),
            }
        )

    if classified > 0 and selected_before_investability == 0:
        issues.append(
            {
                "stage": "allocation_selection",
                "severity": "medium",
                "observed": 0.0,
                "target": "select_from_eligible_classified_candidates",
                "lost_count": classified,
                "reason_codes": ["no_candidate_selected_before_investability"],
                "recommended_action": (
                    "Inspect score, bucket capacity and allocation limits before changing min_final_score."
                ),
            }
        )

    if selected_before_investability > 0 and selected_after_investability == 0:
        issues.append(
            {
                "stage": "investability_gate",
                "severity": "high",
                "observed": 0.0,
                "target": "at_least_one_investable_candidate",
                "lost_count": selected_before_investability,
                "reason_codes": _aggregate_codes(
                    _list(investability_gate.get("rejected")),
                    "rejection_codes",
                ),
                "recommended_action": (
                    "Prioritize liquid mid/large-cap candidates earlier and consider safe same-bucket backfill after a selected symbol is blocked."
                ),
            }
        )

    if selected_after_investability > 0 and exposure_allowed == 0:
        issues.append(
            {
                "stage": "exposure_gate",
                "severity": "high",
                "observed": 0.0,
                "target": "at_least_one_capacity_safe_candidate",
                "lost_count": selected_after_investability,
                "reason_codes": ["all_investable_candidates_blocked_by_exposure"],
                "recommended_action": (
                    "Inspect portfolio capacity, pending orders and protection state; keep exposure limits fail-closed."
                ),
            }
        )

    if backtest_symbols == 0:
        issues.append(
            {
                "stage": "backtest_handoff",
                "severity": "high" if selected_after_investability > 0 else "informational",
                "observed": 0,
                "target": "one_or_more_symbols_when_upstream_gates_allow",
                "lost_count": max(exposure_allowed, selected_after_investability),
                "reason_codes": ["no_preselected_backtest_symbols"],
                "recommended_action": (
                    "Do not bypass Risk/Investability gates; fix the earliest upstream bottleneck first."
                ),
            }
        )

    return issues


def build_profitability_funnel(report: dict[str, Any]) -> dict[str, Any]:
    response = _dict(report.get("response"))
    data = _dict(response.get("data"))
    scanner_metadata = _dict(data.get("scanner_metadata"))
    data_quality_gate = _dict(scanner_metadata.get("scanner_data_quality_gate"))
    opportunity_gate = _dict(scanner_metadata.get("scanner_opportunity_gate"))
    fundamental_cache = _dict(scanner_metadata.get("fundamental_cache"))
    provider_control = _dict(scanner_metadata.get("adaptive_provider_control"))
    bucket_selection = _dict(data.get("bucket_selection"))
    bucket_summary = _dict(bucket_selection.get("summary"))
    allocation_plan = _dict(data.get("allocation_plan"))
    investability_gate = _dict(allocation_plan.get("investability_gate"))
    exposure_gate = _dict(data.get("exposure_gate"))
    exposure_summary = _dict(exposure_gate.get("summary"))
    ranked_candidates = _list(data.get("ranked_candidates"))
    backtest_symbols = [
        str(symbol).upper()
        for symbol in _list(report.get("backtest_symbols"))
        if str(symbol or "").strip()
    ]

    requested = _int(_dict(report.get("request")).get("max_universe"))
    attempted = _int(scanner_metadata.get("attempted_count"), requested)
    analyzed = _int(scanner_metadata.get("analyzed_count"))
    production_candidates = _int(
        data.get("scanner_count"),
        len(_list(data.get("top_10_symbols"))),
    )
    research_candidates = _int(
        data.get("research_candidate_count"),
        len(_list(data.get("research_candidates"))),
    )
    quality_input = _int(
        data_quality_gate.get("original_count"),
        production_candidates + _int(data_quality_gate.get("review_count")),
    )
    data_quality_passed = _int(
        data_quality_gate.get("passed_count"),
        production_candidates,
    )
    opportunity_passed = _int(
        opportunity_gate.get("passed_count"),
        production_candidates,
    )
    deep_analysis = _int(data.get("deep_analysis_count"))
    ranked_count = len(ranked_candidates)
    classified = sum(
        1
        for row in ranked_candidates
        if isinstance(row, dict)
        and str(row.get("strategy_bucket") or "").lower() not in {"", "unassigned"}
        and bool(row.get("evidence_gate_passed", True))
    )
    selected_before_investability = _int(
        bucket_summary.get("selected_before_investability"),
        len(_list(data.get("pre_gate_selected_positions"))),
    )
    selected_after_investability = _int(
        bucket_summary.get("selected_after_investability"),
        selected_before_investability,
    )
    exposure_allowed = _int(
        exposure_summary.get("allowed_count"),
        len(_list(data.get("pre_backtest_selected_positions"))),
    )

    scanner_error_reasons = _dict(scanner_metadata.get("error_categories"))
    data_quality_reasons = _evaluation_reason_counts(data_quality_gate)
    opportunity_reasons = _evaluation_reason_counts(opportunity_gate)
    investability_reasons = _aggregate_codes(
        _list(investability_gate.get("rejected")),
        "rejection_codes",
    )
    top_rejection_reasons = _top_reason_counts(
        scanner_error_reasons,
        data_quality_reasons,
        opportunity_reasons,
        investability_reasons,
    )

    cache_hits = _int(fundamental_cache.get("hit_count"))
    cache_misses = _int(fundamental_cache.get("miss_count"))
    provider_requests_avoided = _int(
        provider_control.get("provider_request_avoided_count")
    )
    provider_requests_saved = cache_hits + provider_requests_avoided

    stages = [
        {"name": "universe_requested", "count": requested},
        {"name": "scanner_attempted", "count": attempted},
        {"name": "scanner_analyzed", "count": analyzed, "conversion_from_previous": _ratio(analyzed, attempted)},
        {"name": "scanner_gate_input", "count": quality_input, "conversion_from_analyzed": _ratio(quality_input, analyzed)},
        {"name": "scanner_analysis_ready", "count": data_quality_passed, "conversion_from_gate_input": _ratio(data_quality_passed, quality_input)},
        {"name": "scanner_production_ready", "count": opportunity_passed, "conversion_from_analysis_ready": _ratio(opportunity_passed, data_quality_passed)},
        {"name": "scanner_research_shadow", "count": research_candidates, "execution_authorized": False},
        {"name": "deep_analysis_success", "count": deep_analysis, "conversion_from_production": _ratio(deep_analysis, production_candidates)},
        {"name": "ranked_candidates", "count": ranked_count},
        {"name": "classified_evidence_eligible", "count": classified, "conversion_from_ranked": _ratio(classified, ranked_count)},
        {"name": "selected_before_investability", "count": selected_before_investability},
        {"name": "investability_passed", "count": selected_after_investability},
        {"name": "exposure_gate_allowed", "count": exposure_allowed},
        {"name": "backtest_handoff", "count": len(backtest_symbols)},
    ]

    bottlenecks = _active_bottlenecks(
        attempted=attempted,
        analyzed=analyzed,
        quality_input=quality_input,
        data_quality_passed=data_quality_passed,
        opportunity_passed=opportunity_passed,
        research_candidates=research_candidates,
        deep_analysis=deep_analysis,
        classified=classified,
        selected_before_investability=selected_before_investability,
        selected_after_investability=selected_after_investability,
        exposure_allowed=exposure_allowed,
        backtest_symbols=len(backtest_symbols),
        scanner_metadata=scanner_metadata,
        bucket_summary=bucket_summary,
        investability_gate=investability_gate,
    )

    return {
        "schema_version": "profitability-funnel.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "portfolio_cycle_id": data.get("report_id"),
        "source_status": report.get("status"),
        "stages": stages,
        "health": {
            "scanner_success_rate": _ratio(analyzed, attempted),
            "scanner_provider_pressure_detected": bool(
                scanner_metadata.get("provider_pressure_detected")
            ),
            "scanner_error_categories": scanner_error_reasons,
            "fundamental_cache": {
                "enabled": bool(fundamental_cache.get("enabled")),
                "schema_version": fundamental_cache.get("schema_version"),
                "ttl_seconds": _int(fundamental_cache.get("ttl_seconds")),
                "entry_count": _int(fundamental_cache.get("entry_count")),
                "hit_count": cache_hits,
                "miss_count": cache_misses,
                "hit_rate": fundamental_cache.get("hit_rate", 0.0),
                "provider_requests_saved_by_cache": cache_hits,
                "provider_requests_avoided_by_circuit_breaker": provider_requests_avoided,
                "provider_requests_saved_or_avoided": provider_requests_saved,
                "production_execution_evidence_reused": bool(
                    fundamental_cache.get("production_execution_evidence_reused", False)
                ),
            },
            "provider_control": {
                "provider_request_attempts": _int(
                    provider_control.get("provider_request_attempts")
                ),
                "recovered_rate_limit_events": _int(
                    provider_control.get("recovered_rate_limit_events")
                ),
                "unresolved_rate_limit_events": _int(
                    provider_control.get("unresolved_rate_limit_events")
                ),
                "provider_circuit_opened": bool(
                    provider_control.get("provider_circuit_opened")
                ),
                "trading_thresholds_relaxed": bool(
                    provider_control.get("trading_thresholds_relaxed", False)
                ),
            },
            "top_rejection_reasons": top_rejection_reasons,
            "data_quality_gate_decision": data_quality_gate.get("decision"),
            "data_quality_threshold": data_quality_gate.get("min_coverage_ratio"),
            "data_quality_threshold_relaxed": bool(data_quality_gate.get("threshold_relaxed", False)),
            "data_quality_coverage_scope_counts": _dict(data_quality_gate.get("coverage_scope_counts")),
            "data_quality_rejection_reasons": data_quality_reasons,
            "opportunity_gate_decision": opportunity_gate.get("decision"),
            "opportunity_rejection_reasons": opportunity_reasons,
            "production_candidate_count": production_candidates,
            "research_candidate_count": research_candidates,
            "shadow_execution_authorized": False,
            "quarantine_count": _int(bucket_summary.get("quarantine_count")),
            "investability_rejection_codes": investability_reasons,
            "backtest_symbols": backtest_symbols,
        },
        "primary_bottleneck": bottlenecks[0] if bottlenecks else None,
        "active_bottlenecks": bottlenecks,
        "safety": {
            "scanner_data_quality_threshold_relaxed": False,
            "production_opportunity_threshold_relaxed": False,
            "risk_thresholds_relaxed": False,
            "investability_thresholds_relaxed": False,
            "shadow_broker_order_authorized": False,
            "purpose": "diagnostic_only",
        },
    }


def render_markdown(funnel: dict[str, Any]) -> str:
    lines = [
        "# Hourly Profitability Funnel Audit",
        "",
        f"Schema: `{funnel.get('schema_version')}`",
        f"Portfolio cycle: `{funnel.get('portfolio_cycle_id') or '-'}`",
        "",
        "## Funnel",
    ]
    for stage in _list(funnel.get("stages")):
        if isinstance(stage, dict):
            lines.append(f"- {stage.get('name')}: `{stage.get('count', 0)}`")

    health = _dict(funnel.get("health"))
    cache = _dict(health.get("fundamental_cache"))
    provider = _dict(health.get("provider_control"))
    lines.extend(
        [
            "",
            "## Health",
            f"- Scanner success rate: `{health.get('scanner_success_rate', 0):.1%}`",
            f"- Provider pressure: `{health.get('scanner_provider_pressure_detected')}`",
            f"- Data quality decision: `{health.get('data_quality_gate_decision') or '-'}`",
            f"- Data quality threshold relaxed: `{health.get('data_quality_threshold_relaxed')}`",
            f"- Production candidates: `{health.get('production_candidate_count', 0)}`",
            f"- Shadow research candidates: `{health.get('research_candidate_count', 0)}`",
            f"- Quarantine count: `{health.get('quarantine_count', 0)}`",
            f"- Backtest symbols: `{', '.join(health.get('backtest_symbols') or []) or '<none>'}`",
            "",
            "## Fundamental cache",
            f"- Enabled: `{cache.get('enabled', False)}`",
            f"- Entries: `{cache.get('entry_count', 0)}`",
            f"- Hits / misses: `{cache.get('hit_count', 0)} / {cache.get('miss_count', 0)}`",
            f"- Hit rate: `{float(cache.get('hit_rate') or 0):.1%}`",
            f"- TTL seconds: `{cache.get('ttl_seconds', 0)}`",
            f"- Provider requests saved by cache: `{cache.get('provider_requests_saved_by_cache', 0)}`",
            f"- Provider requests avoided by circuit breaker: `{cache.get('provider_requests_avoided_by_circuit_breaker', 0)}`",
            f"- Recovered / unresolved rate limits: `{provider.get('recovered_rate_limit_events', 0)} / {provider.get('unresolved_rate_limit_events', 0)}`",
            f"- Production execution evidence reused: `{cache.get('production_execution_evidence_reused', False)}`",
            "",
            "## Gate reasons",
            f"- Data quality: `{json.dumps(health.get('data_quality_rejection_reasons') or {}, sort_keys=True)}`",
            f"- Production opportunity: `{json.dumps(health.get('opportunity_rejection_reasons') or {}, sort_keys=True)}`",
            "",
            "## Top rejection reasons",
        ]
    )
    top_reasons = _list(health.get("top_rejection_reasons"))
    if not top_reasons:
        lines.append("- No rejection reason recorded.")
    else:
        for reason in top_reasons:
            if isinstance(reason, dict):
                lines.append(
                    f"- `{reason.get('code')}`: `{reason.get('count', 0)}`"
                )

    lines.extend(["", "## Bottlenecks"])
    bottlenecks = _list(funnel.get("active_bottlenecks"))
    if not bottlenecks:
        lines.append("- No active funnel bottleneck detected.")
    else:
        for issue in bottlenecks:
            if not isinstance(issue, dict):
                continue
            lines.append(
                f"- **{issue.get('stage')}** ({issue.get('severity')}): "
                f"{issue.get('recommended_action')}"
            )

    lines.extend(
        [
            "",
            "Safety: this report is diagnostic only; it does not relax Scanner, Risk or Investability thresholds and never authorizes Shadow broker orders.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a diagnostic funnel from the hourly Scanner preselection report."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()

    source = json.loads(args.input.read_text(encoding="utf-8"))
    funnel = build_profitability_funnel(source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(funnel, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if args.markdown:
        args.markdown.parent.mkdir(parents=True, exist_ok=True)
        args.markdown.write_text(render_markdown(funnel), encoding="utf-8")

    primary = _dict(funnel.get("primary_bottleneck"))
    print(
        "Profitability funnel audit complete: "
        f"primary_bottleneck={primary.get('stage', 'none')}, "
        f"production_candidates={_dict(funnel.get('health')).get('production_candidate_count', 0)}, "
        f"research_candidates={_dict(funnel.get('health')).get('research_candidate_count', 0)}, "
        f"backtest_symbols={len(_list(_dict(funnel.get('health')).get('backtest_symbols')))}"
    )


if __name__ == "__main__":
    main()

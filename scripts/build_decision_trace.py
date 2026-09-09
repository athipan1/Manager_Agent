"""Explain actual decisions without granting any trading authority."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

try:
    from .build_selection_funnel import build_funnel, obj, rows, number, symbols
    from .portfolio_decision_trace import enrich_portfolio_rows
except ImportError:
    from build_selection_funnel import build_funnel, obj, rows, number, symbols
    from portfolio_decision_trace import enrich_portfolio_rows

GATES = (
    "scanner_pass",
    "score_pass",
    "verdict_pass",
    "bucket_pass",
    "allocation_pass",
    "backtest_pass",
    "risk_pass",
    "execution_authorized",
    "broker_order",
)
WF_METRICS = {
    "window_count": ("evaluated_windows", "min_windows"),
    "profitable_window_rate": ("profitable_window_rate", "min_profitable_window_rate"),
    "median_sharpe_ratio": ("median_sharpe_ratio", "min_median_sharpe_ratio"),
    "median_profit_factor": ("median_profit_factor", "min_median_profit_factor"),
    "worst_max_drawdown": ("worst_max_drawdown", "max_drawdown_floor"),
    "kill_switch_safety": ("total_kill_switch_events", "max_kill_switch_events"),
    "train_eligible_window_rate": ("train_eligible_window_rate", "min_train_eligible_window_rate"),
    "eligible_selection_rate": ("eligible_selection_rate", "min_eligible_selection_rate"),
    "max_abstention_rate": ("abstention_rate", "max_abstention_rate"),
}


def _walk_forward(trace, criteria, scope):
    return {
        "scope": scope,
        "passed": trace.get("passed"),
        "summary": {key: value for key, value in trace.items() if key != "windows"},
        "gates": [
            {
                "field": WF_METRICS.get(key, (key, key))[0],
                "gate": key,
                "passed": passed,
                "observed": trace.get(WF_METRICS.get(key, (key, key))[0]),
                "threshold": criteria.get(WF_METRICS.get(key, (key, key))[1]),
                "reason_code": (scope + "_" + key).upper(),
            }
            for key, passed in obj(trace.get("gates")).items()
        ],
        "windows": rows(trace.get("windows")),
    }


def _backtest_trace(item, root, same_cycle):
    selection = obj(item.get("selection"))
    best = obj(selection.get("best_overall"))
    nested = obj(selection.get("nested_walk_forward"))
    wf = obj(best.get("walk_forward"))
    criteria = obj(selection.get("walk_forward_criteria"))
    parameters = obj(best.get("effective_parameters"))
    metrics = obj(best.get("metrics"))
    contract_issues = []
    if not same_cycle:
        contract_issues.append("BACKTEST_CYCLE_ID_MISMATCH")
    if not selection or not best or not nested:
        contract_issues.append("BACKTEST_SELECTION_EVIDENCE_MISSING")
    strategy = best.get("strategy")
    if strategy and strategy not in {"sma_crossover", "trend_following", "mean_reversion", "breakout"}:
        contract_issues.append("BACKTEST_UNKNOWN_STRATEGY")
    strategy_id = best.get("strategy_id")
    latest_match = (
        nested.get("latest_selection_eligible") is True
        and nested.get("latest_selected_strategy_id") == strategy_id
    )
    return {
        "status": item.get("status"),
        "same_cycle": same_cycle,
        "contract_issues": contract_issues,
        "strategy_id": strategy_id,
        "strategy": strategy,
        "effective_parameters": parameters,
        "all_strategy_results": [
            {
                "strategy_id": candidate.get("strategy_id"),
                "strategy": candidate.get("strategy"),
                "eligible": candidate.get("eligible"),
                "parameters": candidate.get("effective_parameters"),
                "metrics": candidate.get("metrics"),
                "candidate_oos": _walk_forward(obj(candidate.get("walk_forward")), criteria, "candidate_oos"),
                "gates": candidate.get("gates"),
                "disqualification_reasons": candidate.get("disqualification_reasons"),
            }
            for candidate in rows(selection.get("ranked_results"))
        ],
        "signal_generation": {
            "trade_count": metrics.get("trade_count"),
            "trades_observed": number(metrics.get("trade_count")) > 0
            if number(metrics.get("trade_count")) is not None
            else None,
            "fast_window": best.get("fast_window"),
            "slow_window": best.get("slow_window"),
            "buy_signal_count": None,
            "signal_count_status": "not_recorded_by_engine",
        },
        "history": {
            "research_bars": wf.get("available_bars"),
            "minimum_research_bars": root.get("minimum_research_bars"),
            "minimum_total_bars": root.get("minimum_bars"),
            "holdout": item.get("sealed_holdout"),
        },
        "cost_model": {
            key: parameters.get(key)
            for key in (
                "fee_bps",
                "slippage_bps",
                "market_impact_bps",
                "max_volume_participation_pct",
                "annual_risk_free_rate",
                "periods_per_year",
            )
        },
        "research_period_metrics": metrics,
        "metric_units": {
            "return_pct": "decimal",
            "annualized_return": "decimal",
            "max_drawdown": "negative_decimal",
            "sharpe_ratio": "annualized_ratio",
            "sortino_ratio": "annualized_ratio",
            "fee_bps": "basis_points_per_side",
        },
        "research_period_gates": {
            "authority": "diagnostic",
            "criteria": selection.get("selection_criteria"),
            "gates": {
                key: value
                for key, value in obj(best.get("gates")).items()
                if key.startswith("full_period_diagnostic_")
            },
        },
        "candidate_oos": _walk_forward(wf, criteria, "candidate_oos"),
        "nested_outer_oos": _walk_forward(nested, criteria, "nested_outer_oos"),
        "latest_training_selection": {
            "passed": latest_match,
            "selected_strategy_id": nested.get("latest_selected_strategy_id"),
            "training_eligible": nested.get("latest_selection_eligible"),
        },
        "promotion": {
            "eligible": best.get("eligible"),
            "promoted": item.get("promoted"),
            "published": item.get("published"),
            "selection_status": selection.get("selection_status"),
            "rejection_stage": item.get("rejection_stage"),
            "rejection_evidence": item.get("rejection_evidence"),
            "rejection_reason": item.get("rejection_reason"),
            "error": item.get("error"),
            "recorded_reasons": best.get("disqualification_reasons") or [],
        },
        "diagnostic_discrepancies": (
            ["LATEST_SELECTION_REASON_MISCLASSIFIED_AS_OOS_FAILURE"]
            if latest_match
            and "not selected by the latest nested training window"
            in (best.get("disqualification_reasons") or [])
            else []
        ),
    }


def build_report(source, backtest, cycle, review, *, source_run_id=None, final_cycle=None):
    funnel = build_funnel(source, backtest, cycle, source_run_id=source_run_id)
    data = obj(obj(source.get("response")).get("data"))
    ranked = {row.get("symbol"): row for row in rows(data.get("ranked_candidates"))}
    outcomes = {row.get("symbol"): row for row in rows(data.get("analysis_outcomes"))}
    scores = {row.get("symbol"): row for row in funnel["candidate_outcomes"]}
    bt = obj(backtest.get("data"))
    items = {row.get("symbol"): row for row in rows(bt.get("items"))}
    allocated = symbols(data.get("pre_gate_selected_positions"))
    exposure_allowed = symbols(data.get("pre_backtest_selected_positions"))
    eligible = set(funnel["backtest"]["eligible_symbols"])
    same_cycle = funnel["backtest"]["same_cycle"]
    actual = obj(obj(cycle.get("manager_response")).get("data"))
    risk = {row.get("symbol"): row for row in rows(actual.get("risk_approvals"))}
    execution = obj(actual.get("execution"))
    created = symbols(execution.get("created"))
    validation_approved = obj(execution.get("validation")).get("approved") is True
    regime = obj(review.get("market_regime"))
    result = []
    history_symbols = symbols(obj(data.get("pre_backtest_history_gate")).get("evaluations"))
    research_symbols = symbols(data.get("research_candidates"))
    for symbol in sorted(set(ranked) | set(outcomes) | set(items) | history_symbols | research_symbols):
        candidate = ranked.get(symbol, {})
        outcome = outcomes.get(symbol, {})
        score = scores.get(symbol, {})
        evaluated_score, threshold = number(score.get("score")), number(score.get("threshold"))
        approval = risk.get(symbol, {})
        risk_pass = approval.get("approved") if isinstance(approval.get("approved"), bool) else None
        bt_trace = _backtest_trace(items[symbol], bt, same_cycle) if symbol in items else None
        backtest_pass = (symbol in eligible) if same_cycle and symbol in items else None
        if bt_trace and bt_trace["contract_issues"]:
            backtest_pass = None
        gates = {
            "scanner_pass": symbol in set(data.get("top_10_symbols") or ranked),
            "score_pass": evaluated_score >= threshold
            if evaluated_score is not None and threshold is not None
            else None,
            "verdict_pass": str(candidate.get("final_verdict") or outcome.get("final_verdict") or "").lower()
            in {"buy", "strong_buy"}
            if candidate or outcome
            else None,
            "allocation_pass": symbol in allocated if "pre_gate_selected_positions" in data else None,
            "backtest_pass": backtest_pass,
            "risk_pass": risk_pass,
            "execution_authorized": bool(
                symbol in created
                and validation_approved
                and risk_pass is True
                and backtest_pass is True
                and symbol in exposure_allowed
            ),
        }
        trace = outcome.get("decision_trace") or {"status": "not_recorded_in_source_cycle"}
        result.append(
            {
                "symbol": symbol,
                **gates,
                "final_score": evaluated_score,
                "min_final_score": threshold,
                "final_verdict": candidate.get("final_verdict") or outcome.get("final_verdict"),
                "stage_status": {
                    key: "passed"
                    if value is True
                    else "failed"
                    if value is False
                    else "not_evaluated_or_unavailable"
                    for key, value in gates.items()
                },
                "decision_trace": trace,
                "analysis_cache": outcome.get("analysis_cache"),
                "analysis_outcome": {
                    key: value
                    for key, value in outcome.items()
                    if key not in {"decision_trace", "analysis_cache"}
                },
                "market_regime": {
                    "scope": "market_proxy",
                    "symbol": regime.get("symbol"),
                    "regime": regime.get("regime"),
                    "risk_level": regime.get("risk_level"),
                    "recommended_mode": regime.get("recommended_mode"),
                    "signals": regime.get("signals"),
                    "data_quality": regime.get("data_quality"),
                    "reason": regime.get("reason"),
                    "participates_in_directional_verdict": False,
                },
                "allocation": {
                    "bucket": candidate.get("strategy_bucket"),
                    "bucket_confidence": candidate.get("bucket_confidence"),
                    "classification_status": candidate.get("bucket_classification_status"),
                    "evidence_gate_passed": candidate.get("evidence_gate_passed"),
                    "exposure_allowed": symbol in exposure_allowed,
                },
                "backtest": bt_trace,
                "risk": approval or {"status": "not_evaluated"},
                "execution": {
                    "created_order_record": symbol in created,
                    "batch_validation_approved": validation_approved,
                    "status": execution.get("status") or "not_called",
                    "cycle_reason": cycle.get("reason"),
                },
                "rejections": [row for row in funnel["rejections"] if row.get("symbol") == symbol],
            }
        )
    enrich_portfolio_rows(result, data, cycle, obj(final_cycle))
    return {
        "schema_version": "hourly-decision-trace.v2",
        "source_run_id": source_run_id,
        "portfolio_cycle_id": funnel["portfolio_cycle_id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "outcome": funnel["outcome"],
        "counts": funnel["counts"],
        "symbols": result,
        "gate_pass_counts": {gate: sum(row[gate] is True for row in result) for gate in GATES},
        "gate_unknown_counts": {gate: sum(row[gate] is None for row in result) for gate in GATES},
        "safety": {
            "diagnostic_only": True,
            "broker_order_authorized_by_report": False,
            "score_pass_does_not_imply_buy": True,
            "risk_approval_not_inferred_from_backtest": True,
        },
    }


def render_markdown(report):
    lines = [
        "# Per-symbol decision trace",
        "",
        f"Cycle: `{report['portfolio_cycle_id']}`",
        "",
        f"Outcome: **{report['outcome']}**",
        "",
        "PASS / FAIL / N/A are separate stage outcomes; N/A is not approval.",
        "",
        "| Symbol | Score | Verdict | Bucket | Allocation weight | " + " | ".join(GATES) + " |",
        "|---|---:|---|---|---:|" + "---|" * len(GATES),
    ]
    for row in report["symbols"]:
        states = ["PASS" if row[key] is True else "FAIL" if row[key] is False else "N/A" for key in GATES]
        lines.append(
            f"| {row['symbol']} | {row['final_score']} | {row['final_verdict']} | {row['bucket']} | {row['allocation_weight']} | "
            + " | ".join(states)
            + " |"
        )
    for row in report["symbols"]:
        lines += [
            "",
            "## " + row["symbol"],
            "",
            "### Verdict predicates",
            "",
            "| Agent | Field | Observed | Operator | Threshold | Passed | Reason code |",
            "|---|---|---|---|---|---|---|",
        ]
        trace = obj(row["decision_trace"])
        for name, agent in obj(trace.get("agents")).items():
            decision = obj(agent.get("decision"))
            for condition in rows(decision.get("buy_conditions")):
                fields = [
                    name,
                    condition.get("field"),
                    condition.get("observed"),
                    condition.get("operator"),
                    condition.get("threshold"),
                    condition.get("passed"),
                    condition.get("reason_code"),
                ]
                lines.append("| " + " | ".join(str(value) for value in fields) + " |")
        aggregation = obj(trace.get("aggregation"))
        lines += [
            "",
            f"Manager directional score: {aggregation.get('directional_score')} / BUY threshold: "
            f"{obj(aggregation.get('thresholds')).get('buy')}. Final ranking score is not a directional vote.",
            "",
            "Market Regime: "
            + str(row["market_regime"].get("regime"))
            + ". "
            + str(row["market_regime"].get("reason")),
        ]
        bt = row.get("backtest")
        lines += ["", "### Portfolio admission", "",
                  "Bucket: " + str(row["bucket"]) + "; reasons: " + json.dumps(row["allocation"].get("classification_reasons")),
                  "", "Thresholds: bucket score=" + str(row["allocation"].get("bucket_min_final_score"))
                  + ", classification confidence=" + str(row["allocation"].get("classification_min_confidence")),
                  "", "Rule inputs and thresholds: " + json.dumps(row["allocation"].get("classification_rule_trace")),
                  "", "Constraints: " + json.dumps(row["constraints"]),
                  "", "Backtest: " + row["backtest_status"] + "; Risk: " + row["risk_status"]]
        if bt:
            metrics = bt["research_period_metrics"]
            lines += [
                "",
                "### Exact Backtest",
                "",
                f"Strategy: `{bt['strategy_id']}`; research bars: {bt['history']['research_bars']}.",
                "",
                "Costs: " + json.dumps(bt["cost_model"]),
                "",
                "Research-period metrics (returns/drawdown in decimals): "
                + json.dumps(
                    {
                        key: metrics.get(key)
                        for key in (
                            "trade_count",
                            "return_pct",
                            "sharpe_ratio",
                            "sortino_ratio",
                            "max_drawdown",
                            "profit_factor",
                        )
                    }
                ),
                "",
                "| Scope | Gate | Observed | Threshold | Passed |",
                "|---|---|---:|---:|---|",
            ]
            for scope in ("candidate_oos", "nested_outer_oos"):
                for gate in bt[scope]["gates"]:
                    lines.append(
                        f"| {scope} | {gate['gate']} | {gate['observed']} | {gate['threshold']} | {gate['passed']} |"
                    )
            lines += [
                "",
                "Latest training selection: " + json.dumps(bt["latest_training_selection"]),
                "",
                "Promotion: " + json.dumps(bt["promotion"]),
                "",
                "Holdout: " + json.dumps(bt["history"]["holdout"]),
            ]
        lines += ["", "### Recorded blockers", ""]
        lines += [
            f"- `{item['gate']} / {item['reason_code']}`: {item['reason']}" for item in row["rejections"]
        ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    parser.add_argument("--source-run-id", default=os.getenv("GITHUB_RUN_ID"))
    args = parser.parse_args()

    def read(name):
        path = args.reports_dir / name
        return json.loads(path.read_text()) if path.exists() else {}

    report = build_report(
        read("hourly-pre-backtest-discovery.json"),
        read("hourly-backtest-result.json"),
        read("hourly-manager-cycle.json"),
        read("hourly-position-review.json"),
        source_run_id=args.source_run_id,
        final_cycle=read("hourly-portfolio-cycle.json"),
    )
    args.reports_dir.mkdir(parents=True, exist_ok=True)
    (args.reports_dir / "hourly-decision-trace.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False)
    )
    (args.reports_dir / "hourly-decision-trace.md").write_text(render_markdown(report))
    print(json.dumps({"outcome": report["outcome"], "gate_pass_counts": report["gate_pass_counts"]}))


if __name__ == "__main__":
    main()

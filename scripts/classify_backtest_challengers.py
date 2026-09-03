#!/usr/bin/env python3
"""Classify non-production Backtest results for an observation-only challenger lane.

This script never changes Backtest eligibility and never authorizes broker mutation.
It separates near-miss candidates from clearly weak candidates and exposes a small,
deterministic set of strategy configurations for independent Shadow observations.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA_VERSION = "hourly-backtest-challenger.v2"
LANE = "SHADOW_CHALLENGER"
MAX_SHADOW_STRATEGIES_PER_SYMBOL = 3


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def unwrap(report: Mapping[str, Any]) -> dict[str, Any]:
    payload = as_dict(report)
    for _ in range(3):
        inner = payload.get("data")
        if not isinstance(inner, Mapping):
            break
        payload = as_dict(inner)
        if "items" in payload:
            break
    return payload


def normalize_symbol(value: Any) -> str:
    return str(value or "").strip().upper()[:16]


def _failed_candidate_oos(gates: Mapping[str, Any]) -> list[str]:
    return sorted(
        key
        for key, value in gates.items()
        if key.startswith("candidate_oos_") and value is False
    )


def _observation_safe_strategy(row: Mapping[str, Any]) -> bool:
    gates = as_dict(row.get("gates"))
    failed = _failed_candidate_oos(gates)
    safety = (
        gates.get("candidate_oos_kill_switch_safety") is True
        and gates.get("candidate_oos_window_count") is True
        and gates.get("candidate_oos_worst_max_drawdown") is True
    )
    quality = (
        gates.get("candidate_oos_median_profit_factor") is True
        and gates.get("candidate_oos_profitable_window_rate") is True
    )
    return bool(
        safety
        and quality
        and set(failed).issubset({"candidate_oos_median_sharpe_ratio"})
    )


def _shadow_strategy_candidates(selection: Mapping[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    ranked = [as_dict(item) for item in as_list(selection.get("ranked_results"))]
    for rank, row in enumerate(ranked, start=1):
        strategy_id = str(row.get("strategy_id") or "").strip()
        if not strategy_id or strategy_id in seen or not _observation_safe_strategy(row):
            continue
        seen.add(strategy_id)
        candidate_oos = as_dict(row.get("candidate_oos"))
        candidates.append(
            {
                "rank": rank,
                "strategy_id": strategy_id,
                "strategy_name": row.get("strategy") or row.get("strategy_name"),
                "score": row.get("score"),
                "eligible": row.get("eligible") is True,
                "candidate_oos_metrics": {
                    "median_sharpe_ratio": candidate_oos.get("median_sharpe_ratio"),
                    "median_profit_factor": candidate_oos.get("median_profit_factor"),
                    "profitable_window_rate": candidate_oos.get("profitable_window_rate"),
                    "worst_max_drawdown": candidate_oos.get("worst_max_drawdown"),
                    "evaluated_windows": candidate_oos.get("evaluated_windows")
                    or candidate_oos.get("window_count"),
                },
                "failed_candidate_oos_gates": _failed_candidate_oos(
                    as_dict(row.get("gates"))
                ),
                "observation_only": True,
                "production_promotion_authorized": False,
                "risk_execution_authorized": False,
                "broker_order_authorized": False,
            }
        )
        if len(candidates) >= MAX_SHADOW_STRATEGIES_PER_SYMBOL:
            break
    return candidates


def classify_item(item: Mapping[str, Any]) -> dict[str, Any]:
    row = as_dict(item)
    symbol = normalize_symbol(row.get("symbol"))
    status = row.get("status")
    selection = as_dict(row.get("selection"))
    best = as_dict(selection.get("best_overall"))
    gates = as_dict(best.get("gates"))
    candidate_oos = as_dict(best.get("candidate_oos"))
    reasons = [str(x) for x in as_list(best.get("disqualification_reasons"))]
    strategy_candidates = _shadow_strategy_candidates(selection)

    if status == "eligible_strategy_found":
        classification = "production_eligible"
        challenger = False
    elif status != "no_eligible_strategy":
        classification = "operational_failure"
        challenger = False
    else:
        safety_gates = (
            gates.get("candidate_oos_kill_switch_safety") is True
            and gates.get("candidate_oos_window_count") is True
            and gates.get("candidate_oos_worst_max_drawdown") is True
        )
        quality_gates = (
            gates.get("candidate_oos_median_profit_factor") is True
            and gates.get("candidate_oos_profitable_window_rate") is True
        )
        failed_candidate_oos = _failed_candidate_oos(gates)
        allowed_near_miss = set(failed_candidate_oos).issubset(
            {"candidate_oos_median_sharpe_ratio"}
        )
        challenger = bool(
            best
            and safety_gates
            and quality_gates
            and allowed_near_miss
            and row.get("selected_strategy_id") is None
            and row.get("published") is False
        )
        classification = "promising_not_robust" if challenger else "clearly_not_ready"

    if not challenger:
        strategy_candidates = []

    return {
        "symbol": symbol,
        "backtest_status": status,
        "classification": classification,
        "challenger_observation_enabled": challenger,
        "lane": LANE if challenger else None,
        "broker_eligible": status == "eligible_strategy_found",
        "selected_strategy_id": row.get("selected_strategy_id"),
        "best_strategy_id": best.get("strategy_id"),
        "best_strategy_name": best.get("strategy") or best.get("strategy_name"),
        "best_strategy_score": best.get("score"),
        "shadow_strategy_candidate_count": len(strategy_candidates),
        "shadow_strategy_candidates": strategy_candidates,
        "candidate_oos_metrics": {
            "median_sharpe_ratio": candidate_oos.get("median_sharpe_ratio"),
            "median_profit_factor": candidate_oos.get("median_profit_factor"),
            "profitable_window_rate": candidate_oos.get("profitable_window_rate"),
            "worst_max_drawdown": candidate_oos.get("worst_max_drawdown"),
            "evaluated_windows": candidate_oos.get("evaluated_windows")
            or candidate_oos.get("window_count"),
        },
        "failed_candidate_oos_gates": _failed_candidate_oos(gates),
        "disqualification_reasons": reasons,
        "safety": {
            "risk_execution_authorized": status == "eligible_strategy_found",
            "broker_mutation_allowed": status == "eligible_strategy_found",
            "challenger_lane_is_observation_only": challenger,
            "multi_strategy_shadow_only": challenger,
        },
    }


def build_report(report: Mapping[str, Any]) -> dict[str, Any]:
    data = unwrap(report)
    if data.get("all_succeeded") is not True:
        raise ValueError("Backtest report did not prove operational success")
    if data.get("selection_complete") is not True:
        raise ValueError("Backtest selection is incomplete")

    items = [classify_item(as_dict(item)) for item in as_list(data.get("items"))]
    challengers = [item for item in items if item["challenger_observation_enabled"]]
    production = [item for item in items if item["broker_eligible"]]
    clearly_not_ready = [
        item for item in items if item["classification"] == "clearly_not_ready"
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "status": "success",
        "lane": LANE,
        "observation_only": True,
        "production_contract_unchanged": True,
        "max_shadow_strategies_per_symbol": MAX_SHADOW_STRATEGIES_PER_SYMBOL,
        "production_eligible_symbols": [item["symbol"] for item in production],
        "challenger_symbols": [item["symbol"] for item in challengers],
        "clearly_not_ready_symbols": [item["symbol"] for item in clearly_not_ready],
        "shadow_strategy_observation_count": sum(
            int(item.get("shadow_strategy_candidate_count") or 0)
            for item in challengers
        ),
        "items": items,
        "safety": {
            "may_promote_to_risk": False,
            "may_call_execution": False,
            "may_submit_broker_order": False,
            "requires_future_independent_evidence_for_promotion": True,
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--backtest",
        type=Path,
        default=Path("reports/hourly-backtest-result.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/hourly-backtest-challengers.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = json.loads(args.backtest.read_text(encoding="utf-8"))
    result = build_report(report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        "Backtest challenger classification recorded: "
        f"production={result['production_eligible_symbols']} "
        f"challengers={result['challenger_symbols']} "
        f"shadow_strategy_observations={result['shadow_strategy_observation_count']} "
        f"clearly_not_ready={result['clearly_not_ready_symbols']} "
        "broker_mutation_allowed=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

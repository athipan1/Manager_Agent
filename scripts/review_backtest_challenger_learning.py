#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Mapping


SCHEMA_VERSION = "manager-challenger-learning-loop.v1"


def _dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _backtest_items(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    payload = _dict(report)
    data = _dict(payload.get("data"))
    return [dict(row) for row in data.get("items") or [] if isinstance(row, Mapping)]


def _performance_summary(shadow_report: Mapping[str, Any]) -> dict[str, Any]:
    performance = _dict(_dict(shadow_report).get("performance"))
    return _dict(performance.get("data"))


def _strategy_forward_summary(
    performance: Mapping[str, Any], *, strategy_id: str, strategy_name: str | None
) -> dict[str, Any]:
    by_strategy = _dict(performance.get("by_strategy"))
    keys = [strategy_id]
    if strategy_name:
        keys.append(strategy_name)
    matched = next((_dict(by_strategy.get(key)) for key in keys if key in by_strategy), {})
    if not matched:
        return {"observation_count": 0}

    # Drawdown and execution cost are only safe to borrow from the aggregate when
    # the aggregate contains exactly this one strategy. Otherwise withhold them.
    single_strategy = len(by_strategy) == 1
    result = dict(matched)
    if single_strategy:
        result["max_drawdown_pct"] = performance.get("max_drawdown_pct")
        result["average_cost_pct"] = performance.get("average_cost_pct")
    return result


def build_learning_report(
    backtest_report: Mapping[str, Any],
    shadow_report: Mapping[str, Any],
    *,
    build_backtest_evidence: Callable[[Mapping[str, Any]], dict[str, Any]],
    build_forward_evidence: Callable[[Mapping[str, Any]], dict[str, Any]],
    build_learning_request: Callable[..., Any],
    evaluate_learning: Callable[[Any], Any],
) -> dict[str, Any]:
    performance = _performance_summary(shadow_report)
    reviews: list[dict[str, Any]] = []

    for item in _backtest_items(backtest_report):
        if item.get("status") != "no_eligible_strategy":
            continue
        backtest_evidence = build_backtest_evidence(_dict(item.get("selection")))
        if backtest_evidence.get("observation_candidate") is not True:
            continue
        strategy_id = str(backtest_evidence.get("strategy_id") or "").strip()
        if not strategy_id:
            continue
        strategy_name = backtest_evidence.get("strategy_name")
        forward_summary = _strategy_forward_summary(
            performance,
            strategy_id=strategy_id,
            strategy_name=str(strategy_name) if strategy_name else None,
        )
        forward_evidence = build_forward_evidence(forward_summary)
        request = build_learning_request(
            symbol=str(item.get("symbol") or "").upper(),
            strategy_id=strategy_id,
            backtest_evidence=backtest_evidence,
            forward_evidence=forward_evidence,
        )
        decision = evaluate_learning(request)
        decision_payload = (
            decision.model_dump(mode="json")
            if hasattr(decision, "model_dump")
            else dict(decision)
        )
        reviews.append(
            {
                "symbol": str(item.get("symbol") or "").upper(),
                "strategy_id": strategy_id,
                "backtest_evidence": backtest_evidence,
                "forward_evidence": forward_evidence,
                "learning": decision_payload,
            }
        )

    return {
        "schema_version": SCHEMA_VERSION,
        "status": "success",
        "review_count": len(reviews),
        "reviews": reviews,
        "safety": {
            "advisory_only": True,
            "backtest_thresholds_relaxed": False,
            "risk_policy_change_authorized": False,
            "execution_agent_authorized": False,
            "broker_order_authorized": False,
        },
    }


def _load_contracts(repo_root: Path):
    siblings = repo_root.parent
    for repo in ("Backtest_Agent", "Performance_Agent", "Learning_Agent"):
        path = str(siblings / repo)
        if path not in sys.path:
            sys.path.insert(0, path)
    from app.challenger_evidence import build_challenger_evidence
    from app.forward_evidence import build_forward_evidence
    from learning_agent.backtest_shadow_feedback import (
        BacktestShadowFeedbackRequest,
        evaluate_backtest_shadow_feedback,
    )

    return (
        build_challenger_evidence,
        build_forward_evidence,
        BacktestShadowFeedbackRequest,
        evaluate_backtest_shadow_feedback,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backtest", type=Path, default=Path("reports/hourly-backtest-result.json"))
    parser.add_argument("--shadow", type=Path, default=Path("reports/hourly-shadow-lane.json"))
    parser.add_argument("--output", type=Path, default=Path("reports/hourly-challenger-learning.json"))
    args = parser.parse_args()

    builders = _load_contracts(Path(__file__).resolve().parents[1])
    result = build_learning_report(
        json.loads(args.backtest.read_text(encoding="utf-8")),
        json.loads(args.shadow.read_text(encoding="utf-8")),
        build_backtest_evidence=builders[0],
        build_forward_evidence=builders[1],
        build_learning_request=builders[2],
        evaluate_learning=builders[3],
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(
        "Challenger learning review complete: "
        f"reviews={result['review_count']} broker_order_authorized=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

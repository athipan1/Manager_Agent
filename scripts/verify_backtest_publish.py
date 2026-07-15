from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def unwrap_backtest_report(report: Dict[str, Any]) -> Dict[str, Any]:
    """Return BacktestRunAndPublishResult from a standard or legacy response."""
    data = report.get("data")
    return data if isinstance(data, dict) else report


def _verify_multi_strategy_publish(data: Dict[str, Any]) -> Dict[str, Any]:
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("Multi-strategy Backtest batch contained no symbols")

    operational_failures = [
        item for item in items if item.get("status") == "failed"
    ]
    eligible = [
        item
        for item in items
        if item.get("status") == "eligible_strategy_found"
    ]
    ineligible = [
        item
        for item in items
        if item.get("status") == "no_eligible_strategy"
    ]
    unknown = [
        item
        for item in items
        if item.get("status")
        not in {"eligible_strategy_found", "no_eligible_strategy", "failed"}
    ]
    publish_failures = [
        item
        for item in eligible
        if not item.get("selected_strategy_id")
        or item.get("published") is not True
        or item.get("publish_status") != "success"
        or (item.get("database_response") or {}).get("status") != "success"
    ]
    invalid_no_trade = [
        item
        for item in ineligible
        if item.get("selected_strategy_id") is not None
        or item.get("published") is not False
        or item.get("publish_status") != "skipped"
    ]
    expected_strategy_map = {
        str(item.get("symbol") or "").upper(): item.get("selected_strategy_id")
        for item in eligible
    }
    actual_strategy_map = {
        str(symbol).upper(): strategy_id
        for symbol, strategy_id in (
            data.get("strategy_ids_by_symbol") or {}
        ).items()
    }

    if (
        data.get("all_succeeded") is not True
        or data.get("selection_complete") is not True
        or data.get("published") is not True
        or data.get("publish_status") != "success"
        or data.get("published_count") != len(eligible)
        or operational_failures
        or publish_failures
        or invalid_no_trade
        or unknown
        or actual_strategy_map != expected_strategy_map
    ):
        raise ValueError(
            "Multi-strategy Backtest selection or publishing failed: "
            f"operational_failures={operational_failures} "
            f"publish_failures={publish_failures} "
            f"invalid_no_trade={invalid_no_trade} unknown={unknown} "
            f"expected_strategy_map={expected_strategy_map} "
            f"actual_strategy_map={actual_strategy_map}"
        )
    return data


def verify_backtest_publish(report: Dict[str, Any]) -> Dict[str, Any]:
    data = unwrap_backtest_report(report)
    if data.get("mode") == "multi_strategy_selection":
        return _verify_multi_strategy_publish(data)

    items = data.get("items")
    if isinstance(items, list):
        if not items:
            raise ValueError("Backtest batch contained no symbols")
        failures = [
            item
            for item in items
            if item.get("status") != "success"
            or item.get("published") is not True
            or item.get("publish_status") != "success"
            or (item.get("database_response") or {}).get("status")
            != "success"
        ]
        if (
            data.get("all_succeeded") is not True
            or data.get("published") is not True
            or data.get("publish_status") != "success"
            or data.get("published_count") != len(items)
            or failures
        ):
            raise ValueError(
                "One or more batch Backtests were not stored in "
                f"Database_Agent: failures={failures}"
            )
        return data

    published = data.get("published")
    publish_status = data.get("publish_status")
    if published is not True or publish_status != "success":
        raise ValueError(
            "Backtest result was not stored in Database_Agent: "
            f"published={published} publish_status={publish_status}"
        )

    database_response = data.get("database_response") or {}
    if (
        not isinstance(database_response, dict)
        or database_response.get("status") != "success"
    ):
        raise ValueError(
            f"Database_Agent rejected Backtest result: {database_response}"
        )
    return data


def _run_multi_strategy_if_enabled(report_path: Path) -> None:
    if not _bool_env("BACKTEST_MULTI_STRATEGY_ENABLED", True):
        return
    try:
        from scripts.run_multi_strategy_backtests import (
            run_hourly_multi_strategy,
        )
    except ModuleNotFoundError:
        from run_multi_strategy_backtests import run_hourly_multi_strategy

    run_hourly_multi_strategy(report_path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify Backtest_Agent database publishing"
    )
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    if not args.report.exists():
        raise SystemExit(f"Backtest report was not created: {args.report}")

    _run_multi_strategy_if_enabled(args.report)
    report = json.loads(args.report.read_text(encoding="utf-8"))
    try:
        data = verify_backtest_publish(report)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    if data.get("mode") == "multi_strategy_selection":
        print(
            "Multi-strategy Backtests completed: "
            f"eligible_symbols={data.get('eligible_symbols')} "
            f"ineligible_symbols={data.get('ineligible_symbols')} "
            f"strategy_ids_by_symbol={data.get('strategy_ids_by_symbol')} "
            f"published_count={data.get('published_count')}"
        )
    elif isinstance(data.get("items"), list):
        print(
            "Batch Backtests stored successfully: "
            f"symbols={data.get('succeeded_symbols')} "
            f"published_count={data.get('published_count')}"
        )
    else:
        result = data.get("result") or {}
        print(
            "Backtest stored successfully: "
            f"strategy={result.get('strategy')} "
            f"symbols={result.get('symbols')} "
            f"trade_count={(result.get('metrics') or {}).get('trade_count')}"
        )


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict


WALK_FORWARD_MODE = "walk_forward_multi_strategy_selection"
WALK_FORWARD_PROFILE = "rolling_walk_forward_v1"


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def unwrap_backtest_report(report: Dict[str, Any]) -> Dict[str, Any]:
    """Return BacktestRunAndPublishResult from a standard or legacy response."""
    data = report.get("data")
    return data if isinstance(data, dict) else report


def _eligible_walk_forward_evidence(item: Dict[str, Any]) -> bool:
    selection = item.get("selection") if isinstance(item.get("selection"), dict) else {}
    selected = (
        selection.get("best_eligible")
        if isinstance(selection.get("best_eligible"), dict)
        else {}
    )
    evidence = (
        selected.get("walk_forward")
        if isinstance(selected.get("walk_forward"), dict)
        else {}
    )
    gates = evidence.get("gates") if isinstance(evidence.get("gates"), dict) else {}
    return bool(
        selected
        and selected.get("strategy_id") == item.get("selected_strategy_id")
        and selected.get("eligible") is True
        and evidence.get("passed") is True
        and evidence.get("status") == "completed"
        and gates
        and all(value is True for value in gates.values())
    )


def _published_walk_forward_metadata(item: Dict[str, Any]) -> bool:
    payload = (
        item.get("database_payload")
        if isinstance(item.get("database_payload"), dict)
        else {}
    )
    metadata = (
        payload.get("metadata")
        if isinstance(payload.get("metadata"), dict)
        else {}
    )
    validation = (
        metadata.get("walk_forward_validation")
        if isinstance(metadata.get("walk_forward_validation"), dict)
        else {}
    )
    criteria = (
        metadata.get("walk_forward_criteria")
        if isinstance(metadata.get("walk_forward_criteria"), dict)
        else {}
    )
    gates = (
        validation.get("gates")
        if isinstance(validation.get("gates"), dict)
        else {}
    )
    try:
        enough_windows = int(validation.get("evaluated_windows")) >= int(
            criteria.get("min_windows")
        )
    except (TypeError, ValueError):
        enough_windows = False
    return bool(
        metadata.get("validation_profile") == WALK_FORWARD_PROFILE
        and metadata.get("walk_forward_required") is True
        and metadata.get("walk_forward_passed") is True
        and metadata.get("walk_forward_status") == "completed"
        and validation.get("passed") is True
        and validation.get("status") == "completed"
        and gates
        and all(value is True for value in gates.values())
        and enough_windows
    )


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
    walk_forward_failures = (
        [
            item
            for item in eligible
            if not _eligible_walk_forward_evidence(item)
            or not _published_walk_forward_metadata(item)
        ]
        if data.get("mode") == WALK_FORWARD_MODE
        else []
    )
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
    mode_invalid = data.get("mode") == WALK_FORWARD_MODE and (
        data.get("walk_forward_required") is not True
        or data.get("validation_profile") != WALK_FORWARD_PROFILE
    )

    if (
        data.get("all_succeeded") is not True
        or data.get("selection_complete") is not True
        or data.get("published") is not True
        or data.get("publish_status") != "success"
        or data.get("published_count") != len(eligible)
        or operational_failures
        or publish_failures
        or walk_forward_failures
        or invalid_no_trade
        or unknown
        or mode_invalid
        or actual_strategy_map != expected_strategy_map
    ):
        raise ValueError(
            "Multi-strategy Backtest selection or publishing failed: "
            f"operational_failures={operational_failures} "
            f"publish_failures={publish_failures} "
            f"walk_forward_failures={walk_forward_failures} "
            f"invalid_no_trade={invalid_no_trade} unknown={unknown} "
            f"mode_invalid={mode_invalid} "
            f"expected_strategy_map={expected_strategy_map} "
            f"actual_strategy_map={actual_strategy_map}"
        )
    return data


def verify_backtest_publish(report: Dict[str, Any]) -> Dict[str, Any]:
    data = unwrap_backtest_report(report)
    if data.get("mode") in {
        "multi_strategy_selection",
        WALK_FORWARD_MODE,
    }:
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


def _run_strategy_selection_if_enabled(report_path: Path) -> None:
    if not _bool_env("BACKTEST_MULTI_STRATEGY_ENABLED", True):
        return

    if _bool_env("BACKTEST_WALK_FORWARD_ENABLED", True):
        try:
            from scripts.local_backtest_api import managed_backtest_agent
            from scripts.run_walk_forward_multi_strategy import (
                run_hourly_walk_forward_multi_strategy,
            )
        except ModuleNotFoundError:
            from local_backtest_api import managed_backtest_agent
            from run_walk_forward_multi_strategy import (
                run_hourly_walk_forward_multi_strategy,
            )

        with managed_backtest_agent():
            run_hourly_walk_forward_multi_strategy(report_path)
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

    _run_strategy_selection_if_enabled(args.report)
    report = json.loads(args.report.read_text(encoding="utf-8"))
    try:
        data = verify_backtest_publish(report)
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    if data.get("mode") == WALK_FORWARD_MODE:
        print(
            "Walk-forward multi-strategy Backtests completed: "
            f"eligible_symbols={data.get('eligible_symbols')} "
            f"ineligible_symbols={data.get('ineligible_symbols')} "
            f"strategy_ids_by_symbol={data.get('strategy_ids_by_symbol')} "
            f"published_count={data.get('published_count')}"
        )
    elif data.get("mode") == "multi_strategy_selection":
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

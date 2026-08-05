#!/usr/bin/env python3
"""Backtest publish verifier with nested walk-forward compatibility.

The original verifier is retained in ``verify_backtest_publish_legacy``. This
module adds the current nested walk-forward v2 envelope while preserving every
legacy single, batch, multi-strategy, and rolling walk-forward contract.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts import verify_backtest_publish_legacy as _legacy


NESTED_WALK_FORWARD_MODE = "nested_walk_forward_multi_strategy_selection"
NESTED_WALK_FORWARD_PROFILE = "nested_walk_forward_v2"
NESTED_SELECTION_METHOD = "nested_train_select_test_evaluate"

WALK_FORWARD_MODE = _legacy.WALK_FORWARD_MODE
WALK_FORWARD_PROFILE = _legacy.WALK_FORWARD_PROFILE
unwrap_backtest_report = _legacy.unwrap_backtest_report


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _nested_evidence_valid(item: Dict[str, Any]) -> bool:
    strategy_id = item.get("selected_strategy_id")
    selection = _dict(item.get("selection"))
    best = _dict(selection.get("best_eligible"))
    nested = _dict(selection.get("nested_walk_forward"))
    runtime = _dict(item.get("walk_forward"))
    payload_metadata = _dict(_dict(item.get("database_payload")).get("metadata"))
    promotion_gates = _dict(runtime.get("promotion_gates"))
    persisted_gates = _dict(payload_metadata.get("promotion_gates"))

    return bool(
        strategy_id
        and best.get("strategy_id") == strategy_id
        and best.get("eligible") is True
        and nested.get("status") == "completed"
        and nested.get("passed") is True
        and nested.get("selection_method") == NESTED_SELECTION_METHOD
        and nested.get("latest_selected_strategy_id") == strategy_id
        and nested.get("latest_selection_eligible") is True
        and nested.get("overlapping_test_windows") is False
        and runtime.get("validation_profile") == NESTED_WALK_FORWARD_PROFILE
        and runtime.get("selection_method") == NESTED_SELECTION_METHOD
        and runtime.get("walk_forward_required") is True
        and runtime.get("walk_forward_passed") is True
        and runtime.get("walk_forward_status") == "completed"
        and promotion_gates
        and all(value is True for value in promotion_gates.values())
        and payload_metadata.get("validation_profile")
        == NESTED_WALK_FORWARD_PROFILE
        and payload_metadata.get("selection_method") == NESTED_SELECTION_METHOD
        and payload_metadata.get("walk_forward_required") is True
        and payload_metadata.get("walk_forward_passed") is True
        and payload_metadata.get("walk_forward_status") == "completed"
        and persisted_gates
        and all(value is True for value in persisted_gates.values())
    )


def _verify_nested_walk_forward_publish(data: Dict[str, Any]) -> Dict[str, Any]:
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("Nested walk-forward Backtest batch contained no symbols")

    operational_failures = [item for item in items if item.get("status") == "failed"]
    eligible = [
        item for item in items if item.get("status") == "eligible_strategy_found"
    ]
    ineligible = [
        item for item in items if item.get("status") == "no_eligible_strategy"
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
        or _dict(item.get("database_response")).get("status") != "success"
    ]
    evidence_failures = [item for item in eligible if not _nested_evidence_valid(item)]
    invalid_no_trade = [
        item
        for item in ineligible
        if item.get("selected_strategy_id") is not None
        or item.get("published") is not False
        or item.get("publish_status") != "skipped"
        or item.get("database_payload") is not None
        or item.get("database_response") is not None
    ]
    expected_strategy_map = {
        str(item.get("symbol") or "").upper(): item.get("selected_strategy_id")
        for item in eligible
    }
    actual_strategy_map = {
        str(symbol).upper(): strategy_id
        for symbol, strategy_id in _dict(data.get("strategy_ids_by_symbol")).items()
    }
    mode_invalid = not (
        data.get("mode") == NESTED_WALK_FORWARD_MODE
        and data.get("validation_profile") == NESTED_WALK_FORWARD_PROFILE
        and data.get("selection_method") == NESTED_SELECTION_METHOD
        and data.get("walk_forward_required") is True
        and data.get("no_trade_is_success") is True
    )

    if (
        data.get("all_succeeded") is not True
        or data.get("selection_complete") is not True
        or data.get("published") is not True
        or data.get("publish_status") != "success"
        or data.get("published_count") != len(eligible)
        or operational_failures
        or publish_failures
        or evidence_failures
        or invalid_no_trade
        or unknown
        or mode_invalid
        or actual_strategy_map != expected_strategy_map
    ):
        raise ValueError(
            "Nested walk-forward Backtest selection or publishing failed: "
            f"operational_failures={operational_failures} "
            f"publish_failures={publish_failures} "
            f"evidence_failures={evidence_failures} "
            f"invalid_no_trade={invalid_no_trade} unknown={unknown} "
            f"mode_invalid={mode_invalid} "
            f"expected_strategy_map={expected_strategy_map} "
            f"actual_strategy_map={actual_strategy_map}"
        )
    return data


def verify_backtest_publish(report: Dict[str, Any]) -> Dict[str, Any]:
    data = unwrap_backtest_report(report)
    if data.get("mode") == NESTED_WALK_FORWARD_MODE:
        return _verify_nested_walk_forward_publish(data)
    return _legacy.verify_backtest_publish(report)


def main() -> None:
    # Reuse argument parsing, strategy-selection execution, and operator output
    # from the established verifier while substituting this compatibility-aware
    # verification function.
    _legacy.verify_backtest_publish = verify_backtest_publish
    _legacy.main()


if __name__ == "__main__":
    main()

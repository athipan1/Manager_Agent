from __future__ import annotations

import json
from pathlib import Path

from scripts.verify_backtest_evidence_coherence import (
    NESTED_MODE,
    load_authoritative_console_result,
    verify_evidence_coherence,
)


def _nested_data() -> dict:
    return {
        "mode": NESTED_MODE,
        "validation_profile": "nested_walk_forward_v3",
        "selection_method": "nested_train_select_test_evaluate",
        "items": [
            {
                "symbol": "ALL",
                "status": "no_eligible_strategy",
                "selected_strategy_id": None,
            }
        ],
        "eligible_symbols": [],
        "ineligible_symbols": ["ALL"],
        "all_succeeded": True,
        "selection_complete": True,
    }


def test_console_loader_uses_last_result_after_runtime_marker(tmp_path: Path):
    console = tmp_path / "console.json"
    expected = {"status": "success", "data": _nested_data()}
    console.write_text(
        json.dumps({"event": "backtest_runtime_mode", "backtest_mode": "nested_promotion"})
        + "\n"
        + json.dumps(expected),
        encoding="utf-8",
    )

    assert load_authoritative_console_result(console) == expected


def test_matching_nested_evidence_is_coherent_even_with_top_level_runtime_annotation():
    data = _nested_data()
    console = {"status": "success", "data": data}
    persisted = {
        "status": "success",
        "data": json.loads(json.dumps(data)),
        "runtime": {"backtest_mode": "nested_promotion"},
    }

    result = verify_evidence_coherence(console, persisted)

    assert result["status"] == "pass"
    assert result["coherent"] is True
    assert result["console_data_sha256"] == result["persisted_data_sha256"]


def test_legacy_overwrite_is_rejected():
    console = {"status": "success", "data": _nested_data()}
    persisted = {
        "status": "success",
        "data": {
            "mode": "walk_forward_multi_strategy_selection",
            "validation_profile": "rolling_walk_forward_v1",
            "items": [],
        },
    }

    result = verify_evidence_coherence(console, persisted)

    assert result["status"] == "fail"
    assert result["coherent"] is False
    assert "persisted_not_nested_production_evidence" in result["reasons"]
    assert "console_and_persisted_data_diverged" in result["reasons"]


def test_nested_payload_difference_is_rejected():
    console_data = _nested_data()
    persisted_data = json.loads(json.dumps(console_data))
    persisted_data["ineligible_symbols"] = ["DIFFERENT"]

    result = verify_evidence_coherence(
        {"status": "success", "data": console_data},
        {"status": "success", "data": persisted_data},
    )

    assert result["coherent"] is False
    assert result["reasons"] == ["console_and_persisted_data_diverged"]

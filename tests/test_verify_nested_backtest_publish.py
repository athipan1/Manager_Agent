import pytest

from scripts.verify_backtest_publish import verify_backtest_publish


MODE = "nested_walk_forward_multi_strategy_selection"
PROFILE = "nested_walk_forward_v4"
METHOD = "nested_train_select_test_evaluate"


def _no_trade_item(symbol="AAPL"):
    return {
        "symbol": symbol,
        "status": "no_eligible_strategy",
        "selected_strategy_id": None,
        "published": False,
        "publish_status": "skipped",
        "selection": {"best_eligible": None},
        "database_payload": None,
        "database_response": None,
        "error": None,
    }


def _eligible_item(symbol="AAPL"):
    strategy_id = "trend-following-balanced-v1"
    gates = {
        "nested_validation_passed": True,
        "latest_selection_eligible": True,
        "exact_strategy_match": True,
        "independent_test_windows": True,
        "statistical_validation_enabled": True,
    }
    runtime = {
        "validation_profile": PROFILE,
        "selection_method": METHOD,
        "walk_forward_required": True,
        "walk_forward_passed": True,
        "walk_forward_status": "completed",
        "promotion_gates": gates,
    }
    return {
        "symbol": symbol,
        "status": "eligible_strategy_found",
        "selected_strategy_id": strategy_id,
        "published": True,
        "publish_status": "success",
        "selection": {
            "best_eligible": {"strategy_id": strategy_id, "eligible": True},
            "nested_walk_forward": {
                "status": "completed",
                "passed": True,
                "selection_method": METHOD,
                "latest_selected_strategy_id": strategy_id,
                "latest_selection_eligible": True,
                "overlapping_test_windows": False,
            },
        },
        "walk_forward": runtime,
        "database_payload": {"metadata": runtime},
        "database_response": {"status": "success"},
        "error": None,
    }


def _batch(items):
    eligible = [item for item in items if item["status"] == "eligible_strategy_found"]
    ineligible = [item for item in items if item["status"] == "no_eligible_strategy"]
    return {
        "status": "success",
        "data": {
            "mode": MODE,
            "validation_profile": PROFILE,
            "selection_method": METHOD,
            "walk_forward_required": True,
            "no_trade_is_success": True,
            "items": items,
            "eligible_symbols": [item["symbol"] for item in eligible],
            "ineligible_symbols": [item["symbol"] for item in ineligible],
            "failed_symbols": [],
            "strategy_ids_by_symbol": {
                item["symbol"]: item["selected_strategy_id"] for item in eligible
            },
            "all_succeeded": True,
            "selection_complete": True,
            "published": True,
            "publish_status": "success",
            "published_count": len(eligible),
        },
    }


def test_accepts_nested_walk_forward_no_trade_as_safe_success():
    report = _batch([_no_trade_item("ADBE"), _no_trade_item("MSFT")])

    assert verify_backtest_publish(report) is report["data"]


def test_accepts_nested_walk_forward_eligible_publish_with_persisted_evidence():
    report = _batch([_eligible_item(), _no_trade_item("MSFT")])

    assert verify_backtest_publish(report) is report["data"]


def test_rejects_nested_eligible_publish_without_independent_test_windows():
    report = _batch([_eligible_item()])
    report["data"]["items"][0]["selection"]["nested_walk_forward"][
        "overlapping_test_windows"
    ] = True

    with pytest.raises(ValueError, match="evidence_failures"):
        verify_backtest_publish(report)


def test_rejects_nested_no_trade_that_published_fixed_result_as_selected():
    report = _batch([_no_trade_item()])
    item = report["data"]["items"][0]
    item["published"] = True
    item["publish_status"] = "success"
    item["database_payload"] = {"symbol": "AAPL"}

    with pytest.raises(ValueError, match="invalid_no_trade"):
        verify_backtest_publish(report)


def test_rejects_nested_mode_without_v4_profile():
    report = _batch([_no_trade_item()])
    report["data"]["validation_profile"] = "rolling_walk_forward_v1"

    with pytest.raises(ValueError, match="mode_invalid=True"):
        verify_backtest_publish(report)

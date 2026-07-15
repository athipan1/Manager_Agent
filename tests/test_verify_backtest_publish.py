import pytest

from scripts.verify_backtest_publish import (
    unwrap_backtest_report,
    verify_backtest_publish,
)


def successful_data():
    return {
        "published": True,
        "publish_status": "success",
        "database_response": {
            "status": "success",
            "data": {"run": {"run_id": "backtest-1"}},
        },
        "result": {
            "strategy": "sma_crossover",
            "symbols": ["AAPL"],
            "metrics": {"trade_count": 99},
        },
    }


def successful_multi_strategy_data():
    eligible = {
        "symbol": "AAPL",
        "status": "eligible_strategy_found",
        "selected_strategy_id": "trend-following-balanced-v1",
        "published": True,
        "publish_status": "success",
        "database_response": {"status": "success"},
    }
    ineligible = {
        "symbol": "MSFT",
        "status": "no_eligible_strategy",
        "selected_strategy_id": None,
        "published": False,
        "publish_status": "skipped",
        "database_response": None,
    }
    return {
        "mode": "multi_strategy_selection",
        "items": [eligible, ineligible],
        "eligible_symbols": ["AAPL"],
        "ineligible_symbols": ["MSFT"],
        "failed_symbols": [],
        "strategy_ids_by_symbol": {
            "AAPL": "trend-following-balanced-v1"
        },
        "all_succeeded": True,
        "selection_complete": True,
        "published": True,
        "publish_status": "success",
        "published_count": 1,
    }


def successful_walk_forward_data():
    strategy_id = "trend-following-balanced-v1"
    gates = {
        "window_count": True,
        "profitable_window_rate": True,
        "median_sharpe_ratio": True,
        "median_profit_factor": True,
        "worst_max_drawdown": True,
        "kill_switch_safety": True,
    }
    validation = {
        "status": "completed",
        "passed": True,
        "evaluated_windows": 4,
        "profitable_windows": 3,
        "profitable_window_rate": 0.75,
        "stability_score": 0.82,
        "gates": gates,
    }
    eligible = {
        "symbol": "AAPL",
        "status": "eligible_strategy_found",
        "selected_strategy_id": strategy_id,
        "published": True,
        "publish_status": "success",
        "database_response": {"status": "success"},
        "selection": {
            "best_eligible": {
                "strategy_id": strategy_id,
                "eligible": True,
                "walk_forward": validation,
            }
        },
        "database_payload": {
            "metadata": {
                "validation_profile": "rolling_walk_forward_v1",
                "walk_forward_required": True,
                "walk_forward_passed": True,
                "walk_forward_status": "completed",
                "walk_forward_validation": validation,
                "walk_forward_criteria": {"min_windows": 4},
            }
        },
    }
    ineligible = {
        "symbol": "MSFT",
        "status": "no_eligible_strategy",
        "selected_strategy_id": None,
        "published": False,
        "publish_status": "skipped",
        "database_response": None,
        "selection": {"best_eligible": None},
    }
    return {
        "mode": "walk_forward_multi_strategy_selection",
        "validation_profile": "rolling_walk_forward_v1",
        "walk_forward_required": True,
        "items": [eligible, ineligible],
        "eligible_symbols": ["AAPL"],
        "ineligible_symbols": ["MSFT"],
        "failed_symbols": [],
        "strategy_ids_by_symbol": {"AAPL": strategy_id},
        "all_succeeded": True,
        "selection_complete": True,
        "published": True,
        "publish_status": "success",
        "published_count": 1,
    }


def test_unwraps_standard_agent_response_data():
    data = successful_data()
    assert unwrap_backtest_report({"status": "success", "data": data}) is data
    assert verify_backtest_publish({"status": "success", "data": data}) is data


def test_accepts_legacy_flat_report():
    data = successful_data()
    assert verify_backtest_publish(data) is data


def test_accepts_successful_batch_publish():
    item = {
        "symbol": "AAPL",
        "status": "success",
        "published": True,
        "publish_status": "success",
        "database_response": {"status": "success"},
    }
    data = {
        "items": [item, {**item, "symbol": "MSFT"}],
        "all_succeeded": True,
        "published": True,
        "publish_status": "success",
        "published_count": 2,
        "succeeded_symbols": ["AAPL", "MSFT"],
    }

    assert verify_backtest_publish({"status": "success", "data": data}) is data


def test_accepts_multi_strategy_selection_with_valid_no_trade_symbol():
    data = successful_multi_strategy_data()

    assert verify_backtest_publish({"status": "success", "data": data}) is data


def test_accepts_walk_forward_selection_and_persisted_stability():
    data = successful_walk_forward_data()

    assert verify_backtest_publish({"status": "success", "data": data}) is data


def test_rejects_walk_forward_selection_without_database_evidence():
    data = successful_walk_forward_data()
    data["items"][0]["database_payload"]["metadata"].pop(
        "walk_forward_validation"
    )

    with pytest.raises(ValueError, match="walk_forward_failures"):
        verify_backtest_publish({"status": "success", "data": data})


def test_rejects_walk_forward_selection_with_failed_stability_gate():
    data = successful_walk_forward_data()
    selected_validation = data["items"][0]["selection"]["best_eligible"][
        "walk_forward"
    ]
    selected_validation["gates"]["median_sharpe_ratio"] = False

    with pytest.raises(ValueError, match="walk_forward_failures"):
        verify_backtest_publish({"status": "success", "data": data})


def test_rejects_walk_forward_mode_without_required_profile():
    data = successful_walk_forward_data()
    data["validation_profile"] = "full_period_only"

    with pytest.raises(ValueError, match="mode_invalid=True"):
        verify_backtest_publish({"status": "success", "data": data})


def test_rejects_multi_strategy_strategy_map_mismatch():
    data = successful_multi_strategy_data()
    data["strategy_ids_by_symbol"] = {}

    with pytest.raises(ValueError, match="expected_strategy_map"):
        verify_backtest_publish({"status": "success", "data": data})


def test_rejects_multi_strategy_that_publishes_ineligible_symbol():
    data = successful_multi_strategy_data()
    ineligible = data["items"][1]
    ineligible.update(
        selected_strategy_id="sma-crossover-balanced-v1",
        published=True,
        publish_status="success",
    )

    with pytest.raises(ValueError, match="invalid_no_trade"):
        verify_backtest_publish({"status": "success", "data": data})


def test_rejects_partial_batch_publish():
    data = {
        "items": [
            {
                "symbol": "AAPL",
                "status": "success",
                "published": True,
                "publish_status": "success",
                "database_response": {"status": "success"},
            },
            {
                "symbol": "MSFT",
                "status": "failed",
                "published": False,
                "publish_status": "failed",
            },
        ],
        "all_succeeded": False,
        "published": False,
        "publish_status": "partial_failure",
        "published_count": 1,
    }

    with pytest.raises(ValueError):
        verify_backtest_publish({"status": "error", "data": data})


@pytest.mark.parametrize(
    "data",
    [
        {"published": False, "publish_status": "skipped"},
        {
            "published": True,
            "publish_status": "success",
            "database_response": {"status": "failed"},
        },
    ],
)
def test_rejects_unconfirmed_database_publish(data):
    with pytest.raises(ValueError):
        verify_backtest_publish({"status": "success", "data": data})

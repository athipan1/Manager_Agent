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

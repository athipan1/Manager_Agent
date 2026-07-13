import pytest

from scripts.verify_backtest_publish import unwrap_backtest_report, verify_backtest_publish


def successful_data():
    return {
        "published": True,
        "publish_status": "success",
        "database_response": {"status": "success", "data": {"run": {"run_id": "backtest-1"}}},
        "result": {"strategy": "sma_crossover", "symbols": ["AAPL"], "metrics": {"trade_count": 99}},
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
        {"published": True, "publish_status": "success", "database_response": {"status": "failed"}},
    ],
)
def test_rejects_unconfirmed_database_publish(data):
    with pytest.raises(ValueError):
        verify_backtest_publish({"status": "success", "data": data})

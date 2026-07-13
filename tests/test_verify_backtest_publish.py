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

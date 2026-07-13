import pytest

from scripts.run_scanner_preselection import extract_backtest_symbols


def test_extracts_deduplicated_symbols_before_backtest_gate():
    response = {
        "status": "success",
        "data": {
            "pre_backtest_selected_positions": [
                {"symbol": "aapl"},
                {"ticker": "MSFT"},
                {"symbol": "AAPL"},
            ],
            "risk_approvals": [{"symbol": "SHOULD-NOT-BE-USED"}],
        },
    }

    assert extract_backtest_symbols(response) == ["AAPL", "MSFT"]


def test_rejects_failed_manager_response():
    with pytest.raises(ValueError):
        extract_backtest_symbols({"status": "error", "data": {}})

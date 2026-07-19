from scripts.hourly_portfolio_cycle import (
    classify_position_action,
    protection_gaps,
    require_safe_broker_sync,
)

import pytest

from app.hourly_paper_runtime import RuntimeSafetyError


def test_unprotected_position_is_detected_and_replace_is_selected():
    diagnostics = {
        "data": {
            "positions": [
                {
                    "symbol": "AAPL",
                    "protection_status": "unprotected",
                    "unprotected_quantity": 10,
                }
            ]
        }
    }
    assert protection_gaps(diagnostics)[0]["symbol"] == "AAPL"
    assert classify_position_action(
        position={"symbol": "AAPL"},
        protection=diagnostics["data"]["positions"][0],
        portfolio_position={"action": "hold"},
        profit_plan={"primary_action": "hold"},
    ) == "REPLACE_PROTECTION"


def test_stop_quantity_mismatch_and_duplicate_protection_are_gaps():
    for diagnostic in (
        {"symbol": "AAPL", "protection_status": "tp_sl_protected", "quantity_mismatch": True},
        {"symbol": "AAPL", "protection_status": "tp_sl_protected", "duplicate_protection": True},
    ):
        assert protection_gaps({"data": {"positions": [diagnostic]}})


@pytest.mark.parametrize(
    ("profit_action", "expected"),
    [
        ("partial_exit", "PARTIAL_EXIT_RECOMMENDATION"),
        ("exit_all", "EXIT_ALL_RECOMMENDATION"),
    ],
)
def test_automatic_exit_actions_remain_recommendations(profit_action, expected):
    assert classify_position_action(
        position={"symbol": "AAPL"},
        protection={"protection_status": "tp_sl_protected"},
        portfolio_position={"action": "hold"},
        profit_plan={"primary_action": profit_action},
    ) == expected


def test_database_mismatch_blocks_execution():
    with pytest.raises(RuntimeSafetyError):
        require_safe_broker_sync(
            {"data": {"mismatch": {"summary": {"status": "mismatch"}}}},
            stage="pre-execution",
        )


def test_verified_database_sync_allows_progress():
    result = require_safe_broker_sync(
        {"data": {"mismatch": {"summary": {"status": "synced"}}}},
        stage="pre-execution",
    )
    assert result["mismatch"]["summary"]["status"] == "synced"

import pytest

import scripts.hourly_portfolio_cycle as hourly_portfolio_cycle
from app.hourly_paper_runtime import RuntimeSafetyError
from scripts.hourly_portfolio_cycle import (
    CycleClients,
    classify_position_action,
    profit_lifecycle_payload,
    protection_gaps,
    require_safe_broker_sync,
    run_candidate_cycle,
)


def test_hourly_profit_client_uses_api_key(monkeypatch):
    monkeypatch.setenv("PROFIT_AGENT_API_KEY", "hourly-profit-key")

    clients = CycleClients("hourly-correlation-id")

    assert clients.profit.headers == {"X-API-KEY": "hourly-profit-key"}


def test_hourly_market_regime_client_uses_api_key(monkeypatch):
    monkeypatch.setenv("MARKET_REGIME_AGENT_API_KEY", "hourly-market-key")

    clients = CycleClients("hourly-correlation-id")

    assert clients.market.headers == {"X-API-KEY": "hourly-market-key"}


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


def test_blocked_profit_quality_cannot_be_classified_as_hold():
    assert classify_position_action(
        position={"symbol": "AAPL"},
        protection={"protection_status": "tp_sl_protected"},
        portfolio_position={"action": "hold"},
        profit_plan={"primary_action": "review", "decision_status": "blocked"},
    ) == "BLOCKED_PROFIT_DATA_QUALITY"


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


def test_hourly_profit_request_uses_database_lifecycle_identity():
    lifecycle = profit_lifecycle_payload(
        {
            "position_id": 42,
            "position_version": 7,
            "first_target_executed": True,
            "second_target_executed": False,
            "total_exited_quantity": 3,
        },
        account_id="1",
        remaining_quantity=7,
    )

    assert lifecycle == {
        "position_id": "account-1:position-42",
        "position_version": 7,
        "first_target_executed": True,
        "second_target_executed": False,
        "total_exited_quantity": 3,
        "remaining_quantity": 7,
    }


def test_hourly_profit_request_does_not_invent_missing_lifecycle():
    assert (
        profit_lifecycle_payload(
            {"position_id": 42},
            account_id="1",
            remaining_quantity=7,
        )
        is None
    )


class _CandidateClients:
    execution = object()
    manager = object()

    def __init__(self):
        self.manager_payload = None

    def get(self, client, path):
        assert client is self.execution
        assert path == "/broker/protection-diagnostics"
        return {"data": {"positions": []}}

    def post(self, client, path, payload):
        if client is self.manager:
            assert path == "/discover-analyze-trade"
            self.manager_payload = payload
            return {"data": {"execution": {"status": "skipped"}}}
        raise AssertionError(f"unexpected POST: {path}")


def _candidate_preflight():
    return {
        "market_open": True,
        "market_mode": "REVIEW_AND_TRADE",
        "portfolio_cycle_id": "cycle-1",
        "runtime": {"paper_automation": True},
    }


def test_hourly_candidate_execution_is_blocked_when_market_gate_reviews(monkeypatch):
    clients = _CandidateClients()
    monkeypatch.setattr(hourly_portfolio_cycle, "_reconcile", lambda *args, **kwargs: {})

    result = run_candidate_cycle(
        clients,
        preflight=_candidate_preflight(),
        account_id="1",
        review_report={
            "market_regime_gate": {
                "new_entries_allowed": False,
                "decision": "REVIEW",
                "reasons": ["market_regime_data_quality_blocks_trade"],
            }
        },
    )

    assert clients.manager_payload["execute"] is False
    assert result["execute_requested"] is False
    assert result["execution_blocked_by_market_regime"] is True


def test_hourly_candidate_execution_can_proceed_only_when_market_gate_passes(monkeypatch):
    clients = _CandidateClients()
    monkeypatch.setattr(hourly_portfolio_cycle, "_reconcile", lambda *args, **kwargs: {})

    result = run_candidate_cycle(
        clients,
        preflight=_candidate_preflight(),
        account_id="1",
        review_report={
            "market_regime_gate": {
                "new_entries_allowed": True,
                "decision": "PASS",
                "reasons": [],
            }
        },
    )

    assert clients.manager_payload["execute"] is True
    assert result["execute_requested"] is True
    assert result["execution_blocked_by_market_regime"] is False

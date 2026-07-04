from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.models import DiscoverAnalyzeTradeRequest
from app.workflows.guarded_discovery_workflow import (
    _bucket_by_symbol_from_response,
    capture_broker_snapshot,
    run_guarded_discover_analyze_trade_flow,
)


class FakeDBClient:
    sync_payload = {}
    captured_snapshots = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get_broker_sync_status(self, account_id, correlation_id):
        return self.sync_payload

    async def capture_broker_snapshot(self, broker_state, correlation_id):
        self.captured_snapshots.append(broker_state)
        return {"positions_synced": len(broker_state.get("positions") or []), "open_orders_synced": len(broker_state.get("open_orders") or [])}


class FakeExecutionClient:
    broker_payload = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def broker_state(self, account_id, correlation_id):
        return SimpleNamespace(data=self.broker_payload)


def sync_payload(status):
    return {
        "mismatch": {
            "is_synced": status == "synced",
            "summary": {
                "status": status,
                "severity": "ok" if status == "synced" else "warning",
                "recommended_action": "refresh_broker_sync",
            },
            "diagnostics": {"positions": {"missing_in_database": ["AAPL"]}},
        }
    }


def broker_payload():
    return {
        "broker": "ALPACA",
        "paper": True,
        "account": {"broker": "ALPACA", "paper": True, "cash": "93276.77", "equity": "103313.29"},
        "positions": [{"symbol": "ADBE", "qty": "52"}],
        "open_orders": [{"id": "stop-adbe", "symbol": "ADBE", "qty": "52", "status": "new"}],
    }


async def fake_capture_broker_snapshot(account_id, correlation_id, bucket_by_symbol=None):
    return {"status": "captured"}


@pytest.mark.asyncio
async def test_capture_broker_snapshot_posts_execution_state_to_database(monkeypatch):
    FakeDBClient.captured_snapshots = []
    FakeExecutionClient.broker_payload = broker_payload()
    monkeypatch.setattr("app.workflows.guarded_discovery_workflow.DatabaseAgentClient", FakeDBClient)
    monkeypatch.setattr("app.workflows.guarded_discovery_workflow.ExecutionAgentClient", FakeExecutionClient)

    result = await capture_broker_snapshot(1, "corr-1")

    assert result["status"] == "captured"
    assert result["result"] == {"positions_synced": 1, "open_orders_synced": 1}
    assert FakeDBClient.captured_snapshots[0]["source"] == "manager_preflight"
    assert FakeDBClient.captured_snapshots[0]["account_id"] == 1
    assert FakeDBClient.captured_snapshots[0]["positions"][0]["symbol"] == "ADBE"


@pytest.mark.asyncio
async def test_guarded_discovery_blocks_execution_when_database_sync_mismatches(monkeypatch):
    FakeDBClient.sync_payload = sync_payload("mismatch")
    seen = {}

    async def fake_unguarded_flow(request):
        seen["execute"] = request.execute
        return SimpleNamespace(
            status="success",
            agent_type="manager-agent",
            version="1.0.0",
            timestamp=datetime.now(timezone.utc),
            metadata={},
            error=None,
            data={
                "flow": "discover_analyze_trade",
                "selected_positions": [{"symbol": "AAPL"}],
                "risk_approvals": [{"symbol": "AAPL", "approved": True}],
                "execution_candidates": [{"symbol": "AAPL"}],
                "execution": {"status": "not_attempted"},
                "portfolio_summary": {"approved_positions": 1, "rejected_positions": 0, "execution_status": "not_attempted"},
                "legacy": {"trade_decision": {"symbol": "AAPL"}, "risk_approval_id": "risk-1"},
            },
        )

    monkeypatch.setattr("app.workflows.guarded_discovery_workflow.capture_broker_snapshot", fake_capture_broker_snapshot)
    monkeypatch.setattr("app.workflows.guarded_discovery_workflow.DatabaseAgentClient", FakeDBClient)
    monkeypatch.setattr("app.workflows.guarded_discovery_workflow.run_unguarded_discover_analyze_trade_flow", fake_unguarded_flow)

    response = await run_guarded_discover_analyze_trade_flow(DiscoverAnalyzeTradeRequest(account_id=1, execute=True))

    assert seen["execute"] is False
    assert response.data["execution"]["status"] == "blocked"
    assert response.data["execution_candidates"] == []
    assert response.data["risk_approvals"] == []
    assert response.data["broker_snapshot_capture"] == {"status": "captured"}
    assert response.data["portfolio_summary"]["approved_positions"] == 0
    assert response.data["portfolio_summary"]["execution_status"] == "blocked"
    assert response.data["portfolio_summary"]["database_sync_status"] == "mismatch"
    assert response.data["portfolio_summary"]["broker_snapshot_capture_status"] == "captured"
    assert response.data["legacy"]["trade_decision"] is None


@pytest.mark.asyncio
async def test_guarded_discovery_allows_execution_when_database_sync_is_safe(monkeypatch):
    FakeDBClient.sync_payload = sync_payload("synced")
    seen = {}

    async def fake_unguarded_flow(request):
        seen["execute"] = request.execute
        return SimpleNamespace(
            status="success",
            agent_type="manager-agent",
            version="1.0.0",
            timestamp=datetime.now(timezone.utc),
            metadata={},
            error=None,
            data={"portfolio_summary": {}},
        )

    monkeypatch.setattr("app.workflows.guarded_discovery_workflow.capture_broker_snapshot", fake_capture_broker_snapshot)
    monkeypatch.setattr("app.workflows.guarded_discovery_workflow.DatabaseAgentClient", FakeDBClient)
    monkeypatch.setattr("app.workflows.guarded_discovery_workflow.run_unguarded_discover_analyze_trade_flow", fake_unguarded_flow)

    response = await run_guarded_discover_analyze_trade_flow(DiscoverAnalyzeTradeRequest(account_id=1, execute=True))

    assert seen["execute"] is True
    assert response.data["database_sync"] == sync_payload("synced")
    assert response.data["broker_snapshot_capture"] == {"status": "captured"}
    assert response.data["portfolio_summary"]["database_sync_status"] == "synced"
    assert response.data["portfolio_summary"]["broker_snapshot_capture_status"] == "captured"


def test_bucket_hints_include_ranked_candidates_and_bucket_selection():
    data = {
        "ranked_candidates": [
            {"symbol": "ACGL", "score_breakdown": {"strategy_bucket": "value_rebound"}},
            {"symbol": "ADBE", "score_breakdown": {"strategy_bucket": "core_dividend"}},
        ],
        "bucket_selection": {
            "core_dividend": {"selected": [{"symbol": "CINF"}], "overflow": []},
            "news_momentum": {"selected": [{"ticker": "AMSC"}], "overflow": []},
        },
    }

    bucket_by_symbol = _bucket_by_symbol_from_response(data)

    assert bucket_by_symbol["ACGL"] == "value_rebound"
    assert bucket_by_symbol["ADBE"] == "core_dividend"
    assert bucket_by_symbol["CINF"] == "core_dividend"
    assert bucket_by_symbol["AMSC"] == "news_momentum"


def test_bucket_hints_keep_known_held_position_overrides_when_response_has_no_selection():
    bucket_by_symbol = _bucket_by_symbol_from_response({"selected_positions": []})

    assert bucket_by_symbol["ACGL"] == "value_rebound"
    assert bucket_by_symbol["ADBE"] == "core_dividend"
    assert bucket_by_symbol["CINF"] == "core_dividend"

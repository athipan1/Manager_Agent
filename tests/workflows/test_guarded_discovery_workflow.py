from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.models import DiscoverAnalyzeTradeRequest
from app.workflows.guarded_discovery_workflow import run_guarded_discover_analyze_trade_flow


class FakeDBClient:
    sync_payload = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get_broker_sync_status(self, account_id, correlation_id):
        return self.sync_payload


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

    monkeypatch.setattr("app.workflows.guarded_discovery_workflow.DatabaseAgentClient", FakeDBClient)
    monkeypatch.setattr("app.workflows.guarded_discovery_workflow.run_unguarded_discover_analyze_trade_flow", fake_unguarded_flow)

    response = await run_guarded_discover_analyze_trade_flow(DiscoverAnalyzeTradeRequest(account_id=1, execute=True))

    assert seen["execute"] is False
    assert response.data["execution"]["status"] == "blocked"
    assert response.data["execution_candidates"] == []
    assert response.data["risk_approvals"] == []
    assert response.data["portfolio_summary"]["approved_positions"] == 0
    assert response.data["portfolio_summary"]["execution_status"] == "blocked"
    assert response.data["portfolio_summary"]["database_sync_status"] == "mismatch"
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

    monkeypatch.setattr("app.workflows.guarded_discovery_workflow.DatabaseAgentClient", FakeDBClient)
    monkeypatch.setattr("app.workflows.guarded_discovery_workflow.run_unguarded_discover_analyze_trade_flow", fake_unguarded_flow)

    response = await run_guarded_discover_analyze_trade_flow(DiscoverAnalyzeTradeRequest(account_id=1, execute=True))

    assert seen["execute"] is True
    assert response.data["database_sync"] == sync_payload("synced")
    assert response.data["portfolio_summary"]["database_sync_status"] == "synced"

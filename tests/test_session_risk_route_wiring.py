import datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.contracts import StandardAgentResponse
from app.main_modular import app
from app.resilient_client import AgentUnavailable
from app.services.context_service import fetch_session_risk_context, fetch_session_risk_contexts

client = TestClient(app)


@pytest.mark.asyncio
async def test_fetch_session_risk_context_calls_database_snapshot():
    db_client = AsyncMock()
    db_client.get_session_risk_snapshot.return_value = {
        "daily_realized_pnl": -12.5,
        "symbol_trades_today": 1,
        "emergency_halt": False,
    }

    context = await fetch_session_risk_context(db_client, 1, "AAPL", "corr-1")

    db_client.get_session_risk_snapshot.assert_awaited_once_with(1, "corr-1", symbol="AAPL")
    assert context["daily_realized_pnl"] == -12.5
    assert context["symbol_trades_today"] == 1


@pytest.mark.asyncio
async def test_fetch_session_risk_context_fails_closed_in_live():
    db_client = AsyncMock()
    db_client.get_session_risk_snapshot.side_effect = RuntimeError("database down")

    with patch("app.services.context_service.config.TRADING_MODE", "LIVE"):
        with pytest.raises(AgentUnavailable):
            await fetch_session_risk_context(db_client, 1, "AAPL", "corr-1")


@pytest.mark.asyncio
async def test_multi_symbol_session_context_builds_symbol_contexts():
    db_client = AsyncMock()
    db_client.get_session_risk_snapshot.side_effect = [
        {"daily_realized_pnl": -10, "emergency_halt": False},
        {"daily_realized_pnl": -10, "emergency_halt": False},
    ]

    context = await fetch_session_risk_contexts(db_client, 1, ["AAPL", "MSFT", "AAPL"], "corr-1")

    assert set(context["symbol_contexts"].keys()) == {"AAPL", "MSFT"}
    assert context["daily_realized_pnl"] == -10
    assert db_client.get_session_risk_snapshot.await_count == 2


def test_single_route_exposes_session_context(monkeypatch):
    async def fake_run_single_analysis_flow(request, *, dry_run=False):
        return StandardAgentResponse(
            status="success",
            agent_type="manager-agent",
            version="1.0.0",
            timestamp=datetime.datetime.now(datetime.UTC),
            data={"session_risk_context": {"daily_realized_pnl": 0, "emergency_halt": False}},
            metadata={"risk_context_loaded": True},
        )

    monkeypatch.setattr("app.routes.single_analysis.run_single_analysis_flow", fake_run_single_analysis_flow)

    response = client.post("/analyze", json={"ticker": "AAPL"})

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["session_risk_context"]["daily_realized_pnl"] == 0
    assert body["metadata"]["risk_context_loaded"] is True

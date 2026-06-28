from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.contracts import Trade
from app.services.context_service import fetch_session_risk_context


class FakeDatabaseClient:
    def __init__(self):
        self.snapshot = {
            "daily_realized_pnl": 0.0,
            "weekly_realized_pnl": 0.0,
            "consecutive_losses": 0,
            "trades_today": 0,
            "symbol_trades_today": 0,
            "emergency_halt": False,
            "source": "database_agent",
        }
        self.trades = []

    async def get_session_risk_snapshot(self, account_id, correlation_id, symbol=None):
        return dict(self.snapshot)

    async def get_trade_history(self, account_id, correlation_id):
        return list(self.trades)


class FakePerformanceAgentClient:
    payloads = []
    response = {
        "daily_realized_pnl": -750.0,
        "weekly_realized_pnl": -750.0,
        "daily_loss_pct": 0.0075,
        "weekly_loss_pct": 0.0075,
        "consecutive_losses": 2,
        "trades_today": 2,
        "symbol_trades_today": 2,
        "minutes_since_last_loss": 30.0,
        "minutes_since_last_symbol_trade": 30.0,
        "emergency_halt": False,
        "source": "performance_agent",
    }

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def build_session_risk_metrics(self, payload, correlation_id):
        self.__class__.payloads.append({"payload": payload, "correlation_id": correlation_id})
        return dict(self.__class__.response)


class FailingPerformanceAgentClient(FakePerformanceAgentClient):
    async def build_session_risk_metrics(self, payload, correlation_id):
        raise RuntimeError("performance unavailable")


@pytest.mark.asyncio
async def test_fetch_session_risk_context_merges_performance_metrics(monkeypatch):
    FakePerformanceAgentClient.payloads = []
    monkeypatch.setattr("app.services.context_service.config.TRADING_MODE", "PAPER")
    monkeypatch.setattr("app.services.context_service.config.PERFORMANCE_SESSION_RISK_ENABLED", True)
    monkeypatch.setattr("app.services.context_service.PerformanceAgentClient", FakePerformanceAgentClient)
    db_client = FakeDatabaseClient()
    db_client.trades = [
        Trade(
            trade_id="t1",
            account_id=1,
            asset_id="AAPL",
            symbol="AAPL",
            side="buy",
            quantity=Decimal("1"),
            price=Decimal("95"),
            entry_price=Decimal("100"),
            exit_price=Decimal("95"),
            executed_at=datetime(2026, 6, 28, 9, 30, tzinfo=timezone.utc),
        )
    ]

    context = await fetch_session_risk_context(
        db_client,
        account_id=1,
        symbol="AAPL",
        correlation_id="corr-1",
        equity=100000,
    )

    assert context["source"] == "performance_agent"
    assert context["daily_realized_pnl"] == -750.0
    assert context["weekly_loss_pct"] == 0.0075
    assert context["consecutive_losses"] == 2
    assert context["trades_today"] == 2
    assert context["symbol_trades_today"] == 2

    sent_payload = FakePerformanceAgentClient.payloads[0]["payload"]
    assert sent_payload["account_id"] == 1
    assert sent_payload["symbol"] == "AAPL"
    assert sent_payload["equity"] == 100000.0
    assert sent_payload["emergency_halt"] is False
    assert sent_payload["fills"][0]["symbol"] == "AAPL"
    assert sent_payload["fills"][0]["realized_pnl"] == -5.0


@pytest.mark.asyncio
async def test_fetch_session_risk_context_falls_back_to_database_snapshot_in_paper(monkeypatch):
    monkeypatch.setattr("app.services.context_service.config.TRADING_MODE", "PAPER")
    monkeypatch.setattr("app.services.context_service.config.PERFORMANCE_SESSION_RISK_REQUIRED", False)
    monkeypatch.setattr("app.services.context_service.config.PERFORMANCE_SESSION_RISK_ENABLED", True)
    monkeypatch.setattr("app.services.context_service.PerformanceAgentClient", FailingPerformanceAgentClient)
    db_client = FakeDatabaseClient()
    db_client.snapshot["daily_realized_pnl"] = -12.5
    db_client.snapshot["source"] = "database_agent"

    context = await fetch_session_risk_context(
        db_client,
        account_id=1,
        symbol="AAPL",
        correlation_id="corr-2",
        equity=100000,
    )

    assert context["source"] == "database_agent"
    assert context["daily_realized_pnl"] == -12.5


@pytest.mark.asyncio
async def test_fetch_session_risk_context_preserves_manager_emergency_halt(monkeypatch):
    FakePerformanceAgentClient.payloads = []
    monkeypatch.setattr("app.services.context_service.config.TRADING_MODE", "PAPER")
    monkeypatch.setattr("app.services.context_service.config.PERFORMANCE_SESSION_RISK_ENABLED", True)
    monkeypatch.setattr("app.services.context_service.config.MANAGER_EMERGENCY_HALT", True)
    monkeypatch.setattr("app.services.context_service.PerformanceAgentClient", FakePerformanceAgentClient)
    db_client = FakeDatabaseClient()

    context = await fetch_session_risk_context(
        db_client,
        account_id=1,
        symbol="AAPL",
        correlation_id="corr-3",
        equity=100000,
    )

    assert FakePerformanceAgentClient.payloads[0]["payload"]["emergency_halt"] is True
    assert context["emergency_halt"] is True

import pytest
from decimal import Decimal

from app import config
from app.resilient_client import AgentUnavailable
from app.services.context_service import (
    fetch_context_value,
    fetch_session_risk_context,
    fetch_session_risk_contexts,
)


class FakeDbClient:
    def __init__(self, *, orders=None, snapshot=None, fail_orders=False, fail_snapshot=False):
        self.orders = orders if orders is not None else []
        self.snapshot = snapshot if snapshot is not None else {}
        self.fail_orders = fail_orders
        self.fail_snapshot = fail_snapshot

    async def get_orders(self, account_id, correlation_id):
        if self.fail_orders:
            raise RuntimeError("orders unavailable")
        return self.orders

    async def get_session_risk_snapshot(self, account_id, correlation_id, symbol):
        if self.fail_snapshot:
            raise RuntimeError("snapshot unavailable")
        if callable(self.snapshot):
            return self.snapshot(symbol)
        return self.snapshot


def set_trading_mode(monkeypatch, mode):
    monkeypatch.setattr(config, "TRADING_MODE", mode)


@pytest.mark.asyncio
async def test_fetch_context_value_returns_active_order_value(monkeypatch):
    set_trading_mode(monkeypatch, "PAPER")
    db_client = FakeDbClient(
        orders=[
            {"status": "placed", "quantity": 3, "executed_quantity": 1, "price": 10},
            {"status": "filled", "quantity": 3, "executed_quantity": 3, "price": 100},
        ]
    )

    assert await fetch_context_value(db_client, 1, "cid") == Decimal("20")


@pytest.mark.asyncio
async def test_fetch_context_value_falls_back_to_zero_in_paper(monkeypatch):
    set_trading_mode(monkeypatch, "PAPER")
    db_client = FakeDbClient(fail_orders=True)

    assert await fetch_context_value(db_client, 1, "cid") == Decimal("0")


@pytest.mark.asyncio
async def test_fetch_context_value_fails_closed_in_live(monkeypatch):
    set_trading_mode(monkeypatch, "LIVE")
    db_client = FakeDbClient(fail_orders=True)

    with pytest.raises(AgentUnavailable):
        await fetch_context_value(db_client, 1, "cid")


@pytest.mark.asyncio
async def test_fetch_session_risk_context_sets_emergency_halt(monkeypatch):
    set_trading_mode(monkeypatch, "PAPER")
    monkeypatch.setattr(config, "MANAGER_EMERGENCY_HALT", True, raising=False)
    db_client = FakeDbClient(snapshot={"trades_today": 1})

    snapshot = await fetch_session_risk_context(db_client, 1, "AAPL", "cid")

    assert snapshot["trades_today"] == 1
    assert snapshot["emergency_halt"] is True


@pytest.mark.asyncio
async def test_fetch_session_risk_context_falls_back_in_paper(monkeypatch):
    set_trading_mode(monkeypatch, "PAPER")
    monkeypatch.setattr(config, "MANAGER_EMERGENCY_HALT", False, raising=False)
    db_client = FakeDbClient(fail_snapshot=True)

    snapshot = await fetch_session_risk_context(db_client, 1, "AAPL", "cid")

    assert snapshot["daily_realized_pnl"] == 0.0
    assert snapshot["source"] == "manager_fallback"
    assert snapshot["emergency_halt"] is False


@pytest.mark.asyncio
async def test_fetch_session_risk_context_fails_closed_in_live(monkeypatch):
    set_trading_mode(monkeypatch, "LIVE")
    db_client = FakeDbClient(fail_snapshot=True)

    with pytest.raises(AgentUnavailable):
        await fetch_session_risk_context(db_client, 1, "AAPL", "cid")


@pytest.mark.asyncio
async def test_fetch_session_risk_contexts_builds_shared_and_symbol_contexts(monkeypatch):
    set_trading_mode(monkeypatch, "PAPER")

    def snapshot(symbol):
        return {
            "daily_realized_pnl": 1.5,
            "weekly_realized_pnl": 2.5,
            "consecutive_losses": 1,
            "trades_today": 2,
            "minutes_since_last_loss": 30,
            "emergency_halt": False,
            "symbol": symbol,
        }

    db_client = FakeDbClient(snapshot=snapshot)

    result = await fetch_session_risk_contexts(db_client, 1, ["aapl", "AAPL", "msft"], "cid")

    assert result["daily_realized_pnl"] == 1.5
    assert list(result["symbol_contexts"].keys()) == ["AAPL", "MSFT"]
    assert result["symbol_contexts"]["MSFT"]["symbol"] == "MSFT"

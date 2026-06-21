from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app import main
from app.models import ReportDetails


@pytest.mark.asyncio
async def test_fetch_session_risk_context_calls_database_snapshot():
    db_client = AsyncMock()
    db_client.get_session_risk_snapshot.return_value = {
        "daily_realized_pnl": -12.5,
        "weekly_realized_pnl": -20.0,
        "consecutive_losses": 1,
        "trades_today": 2,
        "symbol_trades_today": 1,
        "minutes_since_last_loss": 80,
        "minutes_since_last_symbol_trade": 45,
        "emergency_halt": False,
    }

    context = await main._fetch_session_risk_context(db_client, 1, "AAPL", "corr-1")

    db_client.get_session_risk_snapshot.assert_awaited_once_with(1, "corr-1", symbol="AAPL")
    assert context["daily_realized_pnl"] == -12.5
    assert context["symbol_trades_today"] == 1


@pytest.mark.asyncio
async def test_fetch_session_risk_context_fails_closed_in_live():
    db_client = AsyncMock()
    db_client.get_session_risk_snapshot.side_effect = RuntimeError("database down")

    with patch("app.main.config.TRADING_MODE", "LIVE"):
        with pytest.raises(main.AgentUnavailable):
            await main._fetch_session_risk_context(db_client, 1, "AAPL", "corr-1")


@pytest.mark.asyncio
async def test_fetch_session_risk_context_uses_paper_fallback():
    db_client = AsyncMock()
    db_client.get_session_risk_snapshot.side_effect = RuntimeError("database down")

    with patch("app.main.config.TRADING_MODE", "PAPER"), patch("app.main.config.MANAGER_EMERGENCY_HALT", True):
        context = await main._fetch_session_risk_context(db_client, 1, "AAPL", "corr-1")

    assert context["daily_realized_pnl"] == 0.0
    assert context["weekly_realized_pnl"] == 0.0
    assert context["emergency_halt"] is True
    assert context["source"] == "manager_fallback"


@pytest.mark.asyncio
async def test_multi_symbol_session_context_builds_symbol_contexts():
    db_client = AsyncMock()
    db_client.get_session_risk_snapshot.side_effect = [
        {"daily_realized_pnl": -10, "weekly_realized_pnl": -20, "consecutive_losses": 1, "trades_today": 2, "symbol_trades_today": 1, "emergency_halt": False},
        {"daily_realized_pnl": -10, "weekly_realized_pnl": -20, "consecutive_losses": 1, "trades_today": 2, "symbol_trades_today": 0, "emergency_halt": False},
    ]

    context = await main._fetch_session_risk_contexts(db_client, 1, ["AAPL", "MSFT", "AAPL"], "corr-1")

    assert set(context["symbol_contexts"].keys()) == {"AAPL", "MSFT"}
    assert context["daily_realized_pnl"] == -10
    assert db_client.get_session_risk_snapshot.await_count == 2


@pytest.mark.asyncio
async def test_single_flow_passes_session_context_into_assess_trade():
    class Balance:
        cash_balance = Decimal("10000")

    db_client = AsyncMock()
    db_client.__aenter__.return_value = db_client
    db_client.__aexit__.return_value = None
    db_client.get_account_balance.return_value = Balance()
    db_client.get_positions.return_value = []
    db_client.get_orders.return_value = []
    db_client.get_session_risk_snapshot.return_value = {
        "daily_realized_pnl": 0,
        "weekly_realized_pnl": 0,
        "consecutive_losses": 0,
        "trades_today": 0,
        "symbol_trades_today": 0,
        "minutes_since_last_loss": None,
        "minutes_since_last_symbol_trade": None,
        "emergency_halt": False,
    }

    request = type("Req", (), {"ticker": "AAPL", "account_id": 1})()
    analysis = {
        "ticker": "AAPL",
        "final_verdict": "buy",
        "status": "complete",
        "details": ReportDetails(technical=None, fundamental=None),
        "raw_data": {"technical": {"data": {"current_price": 100, "indicators": {"stop_loss": 95}}}},
    }

    with patch("app.main.DatabaseAgentClient", return_value=db_client), \
            patch("app.main._analyze_single_asset", AsyncMock(return_value=analysis)), \
            patch("app.main._persist_signal", AsyncMock()), \
            patch("app.main._audit_trade_decision", AsyncMock(return_value={})), \
            patch("app.main.LearningAgentClient"), \
            patch("app.main.assess_trade", return_value={"approved": False, "reason": "test", "symbol": "AAPL", "action": "buy"}) as assess_trade:
        await main._run_single_analysis_flow(request, dry_run=True)

    kwargs = assess_trade.call_args.kwargs
    assert kwargs["session_risk_context"]["daily_realized_pnl"] == 0
    assert kwargs["session_risk_context"]["emergency_halt"] is False

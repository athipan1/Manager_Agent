from datetime import datetime, timezone, timedelta

from app.session_risk_context import build_session_risk_context


def test_build_session_risk_context_from_trades():
    now = datetime(2026, 6, 21, 15, 0, tzinfo=timezone.utc)
    trades = [
        {"symbol": "AAPL", "status": "executed", "executed_at": (now - timedelta(minutes=30)).isoformat(), "realized_pnl": -10},
        {"symbol": "AAPL", "status": "executed", "executed_at": (now - timedelta(hours=2)).isoformat(), "realized_pnl": -5},
        {"symbol": "MSFT", "status": "executed", "executed_at": (now - timedelta(days=2)).isoformat(), "realized_pnl": -20},
        {"symbol": "AAPL", "status": "executed", "executed_at": (now - timedelta(days=10)).isoformat(), "realized_pnl": -100},
    ]

    context = build_session_risk_context(account_id=1, symbol="AAPL", orders=[], trades=trades, now=now)

    assert context["daily_realized_pnl"] == -15.0
    assert context["weekly_realized_pnl"] == -35.0
    assert context["consecutive_losses"] == 4
    assert context["trades_today"] == 2
    assert context["symbol_trades_today"] == 2
    assert context["minutes_since_last_loss"] == 30
    assert context["minutes_since_last_symbol_trade"] == 30


def test_build_session_risk_context_stops_loss_streak_on_win():
    now = datetime(2026, 6, 21, 15, 0, tzinfo=timezone.utc)
    trades = [
        {"symbol": "AAPL", "status": "executed", "executed_at": (now - timedelta(minutes=10)).isoformat(), "realized_pnl": 12},
        {"symbol": "AAPL", "status": "executed", "executed_at": (now - timedelta(minutes=30)).isoformat(), "realized_pnl": -5},
    ]

    context = build_session_risk_context(account_id=1, symbol="AAPL", orders=[], trades=trades, now=now)

    assert context["daily_realized_pnl"] == 7.0
    assert context["consecutive_losses"] == 0


def test_build_session_risk_context_uses_order_history_when_trades_missing():
    now = datetime(2026, 6, 21, 15, 0, tzinfo=timezone.utc)
    orders = [
        {"symbol": "AAPL", "status": "executed", "executed_at": (now - timedelta(minutes=20)).isoformat(), "metadata": {"realized_pnl": -7}},
        {"symbol": "AAPL", "status": "pending", "created_at": now.isoformat(), "metadata": {"realized_pnl": -99}},
    ]

    context = build_session_risk_context(account_id=1, symbol="AAPL", orders=orders, trades=None, emergency_halt=True, now=now)

    assert context["daily_realized_pnl"] == -7.0
    assert context["trades_today"] == 1
    assert context["symbol_trades_today"] == 1
    assert context["emergency_halt"] is True

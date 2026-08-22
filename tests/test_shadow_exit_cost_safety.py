import math

from app.services.shadow_trading_service import ShadowTradePlan, build_exit_event


def _plan() -> ShadowTradePlan:
    return ShadowTradePlan(
        shadow_trade_id="trade-1",
        signal_id="signal-1",
        account_id="1",
        correlation_id="shadow-cycle-1",
        symbol="AAPL",
        strategy_id="trend_following",
        decision_price=101.0,
        bid=100.9,
        ask=101.1,
        spread_bps=19.8,
        simulated_fill_price=100.5,
        simulated_slippage_bps=5.0,
        opportunity_score=0.8,
        metadata={"atr_pct": 0.02, "quote_status": "fresh"},
    )


def test_build_exit_event_falls_back_when_signal_decision_price_missing():
    events = [
        {
            "event_type": "signal_decision",
            "shadow_trade_id": "trade-1",
            "account_id": "1",
            "correlation_id": "shadow-cycle-1",
            "signal_id": "signal-1",
            "strategy_id": "trend_following",
            "symbol": "AAPL",
            "side": "buy",
            "decision_price": None,
            "metadata": {"atr_pct": 0.02},
        },
        {
            "event_type": "entry_simulated",
            "simulated_fill_price": 100.5,
            "simulated_slippage_bps": 5.0,
        },
    ]

    result = build_exit_event(
        events=events,
        current_plan=_plan(),
        cycle_id="cycle-1",
        exit_reason="shadow_time_horizon",
    )

    assert result["event_type"] == "exit_simulated"
    assert math.isfinite(result["estimated_cost_pct"])
    assert result["estimated_cost_pct"] >= 0
    assert math.isfinite(result["net_return_pct"])


def test_build_exit_event_uses_signal_reference_price_when_present():
    events = [
        {
            "event_type": "signal_decision",
            "shadow_trade_id": "trade-1",
            "account_id": "1",
            "correlation_id": "shadow-cycle-1",
            "signal_id": "signal-1",
            "strategy_id": "trend_following",
            "symbol": "AAPL",
            "side": "buy",
            "decision_price": 100.0,
            "metadata": {"atr_pct": 0.02},
        },
        {
            "event_type": "entry_simulated",
            "simulated_fill_price": 100.5,
            "simulated_slippage_bps": 50.0,
        },
    ]

    result = build_exit_event(
        events=events,
        current_plan=_plan(),
        cycle_id="cycle-1",
        exit_reason="shadow_time_horizon",
    )

    assert result["estimated_cost_pct"] > 0.005

from scripts.resolve_hourly_trade_gate import build_no_trade_report, resolve_trade_gate


def _preflight(*, market_open: bool) -> dict:
    return {
        "status": "ready",
        "portfolio_cycle_id": "hourly-paper-test-cycle",
        "market_open": market_open,
        "market_mode": "REVIEW_AND_TRADE" if market_open else "PORTFOLIO_REVIEW_ONLY",
        "runtime": {"paper_automation": True},
    }


def _backtest(symbols: list[str]) -> dict:
    return {
        "all_succeeded": True,
        "selection_complete": True,
        "eligible_symbols": symbols,
        "eligible_count": len(symbols),
        "items": [
            {"symbol": symbol, "status": "eligible_strategy_found"}
            for symbol in symbols
        ],
    }


def test_closed_market_stays_research_only_even_with_eligible_strategy() -> None:
    backtest = _backtest(["IA"])
    gate = resolve_trade_gate(_preflight(market_open=False), backtest)

    assert gate["should_trade"] is False
    assert gate["reason"] == "market_closed"
    assert gate["next_action"] == "WAIT_FOR_REGULAR_SESSION"
    assert gate["eligible_symbols"] == ["IA"]

    report = build_no_trade_report(_preflight(market_open=False), gate, backtest)
    assert report["execute_requested"] is False
    assert report["safety"]["risk_called"] is False
    assert report["safety"]["execution_called"] is False
    assert report["broker_orders_submitted"] is False


def test_open_market_routes_eligible_strategy_to_trade_path() -> None:
    gate = resolve_trade_gate(_preflight(market_open=True), _backtest(["IA"]))

    assert gate["should_trade"] is True
    assert gate["reason"] == "eligible_strategy_available"
    assert gate["next_action"] == "CALL_MANAGER_RISK_EXECUTION"
    assert gate["eligible_symbols"] == ["IA"]


def test_open_market_without_eligible_strategy_remains_no_trade() -> None:
    gate = resolve_trade_gate(_preflight(market_open=True), _backtest([]))

    assert gate["should_trade"] is False
    assert gate["reason"] == "no_eligible_strategy"
    assert gate["next_action"] == "OBSERVE_CHALLENGERS_OR_REVIEW_BACKTEST_REJECTIONS"

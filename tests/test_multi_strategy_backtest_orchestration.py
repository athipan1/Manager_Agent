import json

import pytest

from app import config
from scripts.run_multi_strategy_backtests import (
    BALANCED_STRATEGY_IDS,
    _deterministic_run_id,
    _selection_criteria,
    _symbols_from_env,
)


def test_manager_gate_defaults_to_balanced_strategy_identities():
    assert config.BACKTEST_MULTI_STRATEGY_GATE_ENABLED is True
    assert config.BACKTEST_GATE_STRATEGY_IDS == BALANCED_STRATEGY_IDS
    assert "hourly-sma-crossover" not in config.BACKTEST_GATE_STRATEGY_IDS


def test_symbols_from_env_normalizes_and_deduplicates(monkeypatch):
    monkeypatch.setenv("BACKTEST_SYMBOLS", "aapl, MSFT,aapl")
    monkeypatch.setenv("BACKTEST_MAX_SYMBOLS", "10")

    assert _symbols_from_env() == ["AAPL", "MSFT"]


def test_symbols_from_env_rejects_invalid_or_unbounded_input(monkeypatch):
    monkeypatch.setenv("BACKTEST_SYMBOLS", "AAPL,$BAD")
    with pytest.raises(ValueError, match="invalid symbols"):
        _symbols_from_env()

    monkeypatch.setenv("BACKTEST_SYMBOLS", "AAPL,MSFT")
    monkeypatch.setenv("BACKTEST_MAX_SYMBOLS", "1")
    with pytest.raises(ValueError, match="maximum is 1"):
        _symbols_from_env()


def test_selection_criteria_defaults_match_backtest_agent_contract(monkeypatch):
    for name in (
        "BACKTEST_SELECTION_MIN_TRADES",
        "BACKTEST_SELECTION_MIN_ANNUALIZED_RETURN",
        "BACKTEST_SELECTION_MIN_SHARPE_RATIO",
        "BACKTEST_SELECTION_MIN_PROFIT_FACTOR",
        "BACKTEST_SELECTION_MAX_DRAWDOWN_FLOOR",
        "BACKTEST_SELECTION_MIN_EXCESS_RETURN",
        "BACKTEST_SELECTION_MAX_KILL_SWITCH_EVENTS",
    ):
        monkeypatch.delenv(name, raising=False)

    assert _selection_criteria() == {
        "min_trades": 10,
        "min_annualized_return": 0.05,
        "min_sharpe_ratio": 0.80,
        "min_profit_factor": 1.20,
        "max_drawdown_floor": -0.20,
        "min_excess_return": 0.0,
        "max_kill_switch_events": 0,
    }


def test_deterministic_run_id_changes_with_exact_strategy_identity():
    common = {
        "symbol": "AAPL",
        "fingerprint": "dataset-123",
        "parameters": {"fast_window": 10, "slow_window": 30},
        "timeframe": "1d",
        "engine_version": "backtest-agent-0.6.0",
    }

    first = _deterministic_run_id(
        strategy_id="sma-crossover-balanced-v1",
        **common,
    )
    repeated = _deterministic_run_id(
        strategy_id="sma-crossover-balanced-v1",
        **common,
    )
    other = _deterministic_run_id(
        strategy_id="trend-following-balanced-v1",
        **common,
    )

    assert first == repeated
    assert first != other
    assert first.startswith("backtest-selection-")
    json.dumps({"run_id": first})

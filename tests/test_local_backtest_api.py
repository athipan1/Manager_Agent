from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.local_backtest_api import managed_backtest_agent


def test_uses_existing_backtest_service_without_starting_process(monkeypatch):
    monkeypatch.setenv("BACKTEST_AGENT_URL", "http://localhost:8016")
    monkeypatch.setattr("scripts.local_backtest_api._ready", lambda _: True)

    with managed_backtest_agent() as base_url:
        assert base_url == "http://localhost:8016"


def test_refuses_non_local_autostart(monkeypatch):
    monkeypatch.setenv("BACKTEST_AGENT_URL", "http://backtest-agent:8016")
    monkeypatch.setenv("BACKTEST_AGENT_AUTOSTART_LOCAL", "true")
    monkeypatch.setattr("scripts.local_backtest_api._ready", lambda _: False)

    with pytest.raises(RuntimeError, match="localhost"):
        with managed_backtest_agent():
            pass


def test_refuses_missing_backtest_checkout(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("BACKTEST_AGENT_URL", "http://localhost:8016")
    monkeypatch.setenv("BACKTEST_AGENT_AUTOSTART_LOCAL", "true")
    monkeypatch.setenv("BACKTEST_AGENT_REPO", str(tmp_path / "missing"))
    monkeypatch.setattr("scripts.local_backtest_api._ready", lambda _: False)

    with pytest.raises(RuntimeError, match="checkout is unavailable"):
        with managed_backtest_agent():
            pass


def test_disabled_autostart_fails_closed(monkeypatch):
    monkeypatch.setenv("BACKTEST_AGENT_URL", "http://localhost:8016")
    monkeypatch.setenv("BACKTEST_AGENT_AUTOSTART_LOCAL", "false")
    monkeypatch.setattr("scripts.local_backtest_api._ready", lambda _: False)

    with pytest.raises(RuntimeError, match="autostart is disabled"):
        with managed_backtest_agent():
            pass

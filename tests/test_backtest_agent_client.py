import pytest

from app.backtest_agent_client import BacktestAgentClient


def standard_response(data):
    return {
        "status": "success",
        "agent_type": "backtest-agent",
        "version": "0.1.0",
        "timestamp": "2026-01-01T00:00:00Z",
        "data": data,
    }


@pytest.mark.asyncio
async def test_backtest_client_calls_run_endpoint(monkeypatch):
    calls = []

    async def fake_post(self, path, correlation_id, json_data):
        calls.append((path, correlation_id, json_data))
        return standard_response({"ok": True})

    monkeypatch.setattr(BacktestAgentClient, "_post", fake_post)

    client = BacktestAgentClient()
    result = await client.run_backtest({"symbols": ["AAPL"]}, "cid-1")

    assert result == {"ok": True}
    assert calls == [("/backtest/run", "cid-1", {"symbols": ["AAPL"]})]


@pytest.mark.asyncio
async def test_backtest_client_calls_compare_endpoint(monkeypatch):
    calls = []

    async def fake_post(self, path, correlation_id, json_data):
        calls.append(path)
        return standard_response({"ranked_results": []})

    monkeypatch.setattr(BacktestAgentClient, "_post", fake_post)

    client = BacktestAgentClient()
    result = await client.compare_strategies({"candidates": []}, "cid-2")

    assert result == {"ranked_results": []}
    assert calls == ["/backtest/compare"]


@pytest.mark.asyncio
async def test_backtest_client_adds_missing_timestamp(monkeypatch):
    async def fake_post(self, path, correlation_id, json_data):
        return {
            "status": "success",
            "agent_type": "backtest-agent",
            "version": "0.1.0",
            "data": {"ranked_results": [], "best": None},
            "error": None,
        }

    monkeypatch.setattr(BacktestAgentClient, "_post", fake_post)

    client = BacktestAgentClient()
    result = await client.compare_strategies({"candidates": []}, "cid-6")

    assert result == {"ranked_results": [], "best": None}


@pytest.mark.asyncio
async def test_backtest_client_calls_walk_forward_and_report(monkeypatch):
    calls = []

    async def fake_post(self, path, correlation_id, json_data):
        calls.append(path)
        return standard_response({"ok": True})

    monkeypatch.setattr(BacktestAgentClient, "_post", fake_post)

    client = BacktestAgentClient()
    await client.walk_forward({"symbols": ["AAPL"]}, "cid-3")
    await client.build_report({"result": {}}, "cid-4")

    assert calls == ["/backtest/walk-forward", "/backtest/report"]


@pytest.mark.asyncio
async def test_backtest_client_calls_health(monkeypatch):
    async def fake_get(self, path, correlation_id):
        return standard_response({"service": "backtest-agent"})

    monkeypatch.setattr(BacktestAgentClient, "_get", fake_get)

    client = BacktestAgentClient()
    result = await client.health("cid-5")

    assert result == {"service": "backtest-agent"}

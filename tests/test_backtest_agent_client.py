import pytest

from app.backtest_agent_client import BacktestAgentClient


@pytest.mark.asyncio
async def test_backtest_client_calls_run_endpoint(monkeypatch):
    calls = []

    async def fake_post(self, path, correlation_id, json_data):
        calls.append((path, correlation_id, json_data))
        return {"status": "success", "data": {"ok": True}}

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
        return {"status": "success", "data": {"ranked_results": []}}

    monkeypatch.setattr(BacktestAgentClient, "_post", fake_post)

    client = BacktestAgentClient()
    result = await client.compare_strategies({"candidates": []}, "cid-2")

    assert result == {"ranked_results": []}
    assert calls == ["/backtest/compare"]


@pytest.mark.asyncio
async def test_backtest_client_calls_walk_forward_and_report(monkeypatch):
    calls = []

    async def fake_post(self, path, correlation_id, json_data):
        calls.append(path)
        return {"status": "success", "data": {"ok": True}}

    monkeypatch.setattr(BacktestAgentClient, "_post", fake_post)

    client = BacktestAgentClient()
    await client.walk_forward({"symbols": ["AAPL"]}, "cid-3")
    await client.build_report({"result": {}}, "cid-4")

    assert calls == ["/backtest/walk-forward", "/backtest/report"]


@pytest.mark.asyncio
async def test_backtest_client_calls_health(monkeypatch):
    async def fake_get(self, path, correlation_id):
        return {"status": "success", "data": {"service": "backtest-agent"}}

    monkeypatch.setattr(BacktestAgentClient, "_get", fake_get)

    client = BacktestAgentClient()
    result = await client.health("cid-5")

    assert result == {"service": "backtest-agent"}

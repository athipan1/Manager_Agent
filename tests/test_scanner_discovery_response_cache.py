import pytest

from app.scanner_client import (
    SCANNER_DISCOVERY_RESPONSE_CACHE,
    ScannerAgentClient,
    clear_scanner_discovery_cache,
)


def scanner_success_response(correlation_id="scanner-first-call"):
    return {
        "status": "success",
        "agent_type": "scanner",
        "version": "1.0.0",
        "schema_version": "1.0",
        "timestamp": "2026-07-15T00:00:00Z",
        "correlation_id": correlation_id,
        "data": {
            "scan_type": "best_fundamentals",
            "count": 2,
            "candidates": [
                {
                    "symbol": "ACGL",
                    "candidate_score": 0.919,
                    "recommendation_hint": "FUNDAMENTAL_TOP_10",
                    "raw_scores": {"fundamental_score": 91.9},
                    "metadata": {"source": "real_market_fundamental_discovery"},
                },
                {
                    "symbol": "ADBE",
                    "candidate_score": 0.882,
                    "recommendation_hint": "FUNDAMENTAL_TOP_10",
                    "raw_scores": {"fundamental_score": 88.2},
                    "metadata": {"source": "real_market_fundamental_discovery"},
                },
            ],
            "metadata": {"selected_universe_count": 1000},
            "errors": {},
        },
        "metadata": {"trading_mode": "PAPER"},
        "error": None,
    }


@pytest.fixture(autouse=True)
def reset_scanner_discovery_cache(monkeypatch):
    clear_scanner_discovery_cache()
    monkeypatch.setenv("SCANNER_DISCOVERY_CACHE_TTL_SECONDS", "1800")
    yield
    clear_scanner_discovery_cache()


@pytest.mark.asyncio
async def test_identical_discovery_reuses_first_successful_response(monkeypatch):
    client = ScannerAgentClient()
    calls = []

    async def fake_post(url, correlation_id, json_data, **kwargs):
        calls.append((url, correlation_id, json_data, kwargs))
        return scanner_success_response(correlation_id)

    monkeypatch.setattr(client, "_post", fake_post)
    try:
        first = await client.discover_best_fundamentals(
            correlation_id="pre-backtest",
            max_universe=1000,
            top_n=10,
            exchange="NASDAQ",
            max_workers=10,
        )
        second = await client.discover_best_fundamentals(
            correlation_id="risk-execution",
            max_universe=1000,
            top_n=10,
            exchange="NASDAQ",
            max_workers=10,
        )
    finally:
        await client._client.aclose()

    assert len(calls) == 1
    assert first.correlation_id == "pre-backtest"
    assert second.correlation_id == "risk-execution"
    assert second.metadata["scanner_discovery_cache_hit"] is True
    assert second.metadata["scanner_discovery_cache_key"] == {
        "max_universe": 1000,
        "top_n": 10,
        "exchange": "NASDAQ",
        "max_workers": 10,
    }
    assert [candidate.symbol for candidate in second.data.candidates] == [
        "ACGL",
        "ADBE",
    ]


@pytest.mark.asyncio
async def test_changed_discovery_parameters_do_not_reuse_cache(monkeypatch):
    client = ScannerAgentClient()
    calls = []

    async def fake_post(url, correlation_id, json_data, **kwargs):
        calls.append(json_data)
        return scanner_success_response(correlation_id)

    monkeypatch.setattr(client, "_post", fake_post)
    try:
        await client.discover_best_fundamentals(
            correlation_id="first",
            max_universe=1000,
            top_n=10,
            exchange="NASDAQ",
            max_workers=10,
        )
        await client.discover_best_fundamentals(
            correlation_id="different-top-n",
            max_universe=1000,
            top_n=5,
            exchange="NASDAQ",
            max_workers=10,
        )
    finally:
        await client._client.aclose()

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_expired_discovery_response_is_refetched(monkeypatch):
    client = ScannerAgentClient()
    calls = []

    async def fake_post(url, correlation_id, json_data, **kwargs):
        calls.append(correlation_id)
        return scanner_success_response(correlation_id)

    monkeypatch.setattr(client, "_post", fake_post)
    try:
        await client.discover_best_fundamentals(
            correlation_id="first",
            max_universe=1000,
            top_n=10,
            exchange="NASDAQ",
            max_workers=10,
        )
        cache_entry = next(iter(SCANNER_DISCOVERY_RESPONSE_CACHE.values()))
        cache_entry["stored_at"] -= 3600

        second = await client.discover_best_fundamentals(
            correlation_id="after-expiry",
            max_universe=1000,
            top_n=10,
            exchange="NASDAQ",
            max_workers=10,
        )
    finally:
        await client._client.aclose()

    assert calls == ["first", "after-expiry"]
    assert "scanner_discovery_cache_hit" not in second.metadata

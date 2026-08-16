from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

import pytest

from app.hourly_paper_runtime import RuntimeSafetyError
from scripts.hourly_market_regime_data import fetch_market_regime_inputs


def _bar(index: int) -> dict:
    close = 400.0 + index
    return {
        "t": f"2025-01-{(index % 28) + 1:02d}T00:00:00Z",
        "o": close - 1,
        "h": close + 2,
        "l": close - 2,
        "c": close,
        "v": 1000 + index,
    }


def test_market_regime_uses_explicit_history_window(monkeypatch):
    requested_paths = []

    def response(self, path, **kwargs):
        requested_paths.append(path)
        return {"bars": [_bar(index) for index in range(220)], "next_page_token": None}

    monkeypatch.setattr(
        "scripts.hourly_market_regime_data.JsonHttpClient.request",
        response,
    )

    result = fetch_market_regime_inputs(
        api_key_id="key",
        secret_key="secret",
        correlation_id="cycle",
        now=datetime(2026, 7, 26, tzinfo=timezone.utc),
    )

    query = parse_qs(urlsplit(requested_paths[0]).query)
    assert query["timeframe"] == ["1Day"]
    assert query["start"] == ["2025-03-13T00:00:00Z"]
    assert query["end"] == ["2026-07-26T00:00:00Z"]
    assert query["feed"] == ["iex"]
    assert query["limit"] == ["10000"]
    assert result["bar_count"] == 220
    assert result["data_feed"] == "iex"
    assert result["market_data_timestamp"] == "2026-07-26T00:00:00+00:00"
    assert result["sma_200"] > 0
    assert result["atr_pct"] > 0


def test_market_regime_follows_next_page_token(monkeypatch):
    requested_paths = []

    def response(self, path, **kwargs):
        requested_paths.append(path)
        if len(requested_paths) == 1:
            return {
                "bars": [_bar(index) for index in range(120)],
                "next_page_token": "next page/token",
            }
        return {
            "bars": [_bar(index) for index in range(120, 220)],
            "next_page_token": None,
        }

    monkeypatch.setattr(
        "scripts.hourly_market_regime_data.JsonHttpClient.request",
        response,
    )

    result = fetch_market_regime_inputs(
        api_key_id="key",
        secret_key="secret",
        correlation_id="cycle",
        now=datetime(2026, 7, 26, tzinfo=timezone.utc),
    )

    assert len(requested_paths) == 2
    second_query = parse_qs(urlsplit(requested_paths[1]).query)
    assert second_query["page_token"] == ["next page/token"]
    assert result["bar_count"] == 220


def test_market_regime_fails_closed_with_actual_bar_count(monkeypatch):
    monkeypatch.setattr(
        "scripts.hourly_market_regime_data.JsonHttpClient.request",
        lambda self, path, **kwargs: {"bars": [_bar(index) for index in range(10)]},
    )

    with pytest.raises(RuntimeSafetyError, match=r"received=10, required=200"):
        fetch_market_regime_inputs(
            api_key_id="key",
            secret_key="secret",
            correlation_id="cycle",
            now=datetime(2026, 7, 26, tzinfo=timezone.utc),
        )

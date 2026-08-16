"""Reliable Alpaca daily-bar retrieval for hourly Market Regime inputs."""

from __future__ import annotations

import urllib.parse
from datetime import datetime, timedelta, timezone
from typing import Any

from app.hourly_paper_runtime import (
    ALPACA_DATA_API_URL,
    JsonHttpClient,
    RuntimeSafetyError,
)

MINIMUM_BARS = 200
TARGET_BARS = 220
MAX_PAGES = 5
LOOKBACK_DAYS = 500


def _validated_rows(rows: list[Any]) -> list[dict[str, Any]]:
    valid: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if all(row.get(field) is not None for field in ("c", "h", "l")):
            valid.append(row)
    return valid


def fetch_market_regime_inputs(
    *,
    api_key_id: str,
    secret_key: str,
    correlation_id: str,
    symbol: str = "SPY",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fetch enough historical daily bars and derive deterministic regime inputs.

    ``market_data_timestamp`` is the observation/fetch timestamp, not the daily
    candle timestamp. That distinction lets Market_Regime_Agent measure whether
    Manager's evidence snapshot is fresh while the underlying strategy remains a
    daily-bar regime model.
    """
    normalized_symbol = symbol.strip().upper()
    if not normalized_symbol or not normalized_symbol.replace(".", "").isalnum():
        raise RuntimeSafetyError("Market regime symbol is invalid.")

    end = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    start = end - timedelta(days=LOOKBACK_DAYS)
    client = JsonHttpClient(
        base_url=ALPACA_DATA_API_URL,
        service_name="Alpaca Market Data",
        headers={
            "APCA-API-KEY-ID": api_key_id,
            "APCA-API-SECRET-KEY": secret_key,
        },
        timeout_seconds=20,
    )

    bars: list[dict[str, Any]] = []
    page_token = ""
    for _ in range(MAX_PAGES):
        query = {
            "timeframe": "1Day",
            "start": start.isoformat().replace("+00:00", "Z"),
            "end": end.isoformat().replace("+00:00", "Z"),
            "limit": "10000",
            "adjustment": "raw",
            "feed": "iex",
            "sort": "asc",
        }
        if page_token:
            query["page_token"] = page_token
        path = (
            f"/v2/stocks/{urllib.parse.quote(normalized_symbol, safe='')}/bars?"
            + urllib.parse.urlencode(query)
        )
        payload = client.request(path, correlation_id=correlation_id)
        if not isinstance(payload, dict):
            raise RuntimeSafetyError("Alpaca Market Data response is invalid.")
        page_rows = payload.get("bars")
        if not isinstance(page_rows, list):
            raise RuntimeSafetyError("Alpaca Market Data bars payload is invalid.")
        bars.extend(_validated_rows(page_rows))
        if len(bars) >= TARGET_BARS:
            break
        page_token = str(payload.get("next_page_token") or "").strip()
        if not page_token:
            break

    if len(bars) < MINIMUM_BARS:
        raise RuntimeSafetyError(
            "Alpaca Market Data returned insufficient daily history "
            f"for Market_Regime_Agent (received={len(bars)}, required={MINIMUM_BARS})."
        )

    bars = bars[-TARGET_BARS:]
    closes = [float(row["c"]) for row in bars]
    if len(closes) < MINIMUM_BARS:
        raise RuntimeSafetyError("Market regime close-price history is incomplete.")

    atr_rows = bars[-15:]
    previous_close = float(atr_rows[0]["c"])
    true_ranges: list[float] = []
    for row in atr_rows[1:]:
        high = float(row["h"])
        low = float(row["l"])
        close = float(row["c"])
        true_ranges.append(
            max(high - low, abs(high - previous_close), abs(low - previous_close))
        )
        previous_close = close

    price = closes[-1]
    atr = sum(true_ranges) / len(true_ranges)
    return {
        "symbol": normalized_symbol,
        "price": round(price, 6),
        "sma_50": round(sum(closes[-50:]) / 50, 6),
        "sma_200": round(sum(closes[-200:]) / 200, 6),
        "atr_pct": round(atr / price, 8) if price > 0 else None,
        "market_data_timestamp": end.isoformat(),
        "bar_count": len(bars),
        "data_feed": "iex",
    }

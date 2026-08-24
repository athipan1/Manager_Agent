#!/usr/bin/env python3
"""Inject a provider-free US market snapshot fixture into a checked-out Scanner_Agent.

Temporary PR-smoke helper only. It modifies the Scanner checkout in the Actions
workspace before Docker build. It must never be used by production Hourly runs.
"""

from __future__ import annotations

import argparse
from pathlib import Path

MARKER = "SIMULATED_MARKET_SMOKE_V3"

BLOCK = r'''    # SIMULATED_MARKET_SMOKE_V3: ephemeral CI-only fixture.
    # Return before Alpaca/yfinance are touched so a closed market or provider
    # outage cannot hide downstream orchestration bugs in this smoke test.
    if _is_us_equity_exchange(exchange):
        simulated_price = float(100 + (sum(ord(ch) for ch in clean_symbol) % 50))
        simulated_spread_bps = 8.0
        half_spread = simulated_price * simulated_spread_bps / 20_000.0
        simulated_bid = simulated_price - half_spread
        simulated_ask = simulated_price + half_spread
        snapshot.update(
            {
                "exchange": str(exchange or "NASDAQ").upper(),
                "currentPrice": simulated_price,
                "regularMarketPrice": simulated_price,
                "previousClose": round(simulated_price * 0.99, 8),
                "marketState": "REGULAR",
                "marketCap": 1_000_000_000_000.0,
                "averageVolume": 2_500_000.0,
                "regularMarketVolume": 1_250_000.0,
                "sector": "Technology",
                "industry": "Software",
                "trailingPE": 25.0,
                "forwardPE": 22.0,
                "pegRatio": 1.5,
                "priceToBook": 7.0,
                "revenueGrowth": 0.15,
                "earningsGrowth": 0.18,
                "returnOnEquity": 0.25,
                "returnOnAssets": 0.12,
                "debtToEquity": 40.0,
                "profitMargins": 0.20,
                "freeCashflow": 10_000_000_000.0,
                "historicalAtr14": round(simulated_price * 0.02, 8),
                "historicalAtrPct": 0.02,
                "historicalAverageVolume20d": 2_500_000.0,
                "historyBarCount": 45,
                "alpacaBidPrice": round(simulated_bid, 6),
                "alpacaAskPrice": round(simulated_ask, 6),
                "alpacaMidpoint": simulated_price,
                "alpacaSpread": round(simulated_ask - simulated_bid, 6),
                "alpacaSpreadBps": simulated_spread_bps,
                "alpacaBidSize": 500.0,
                "alpacaAskSize": 500.0,
                "alpacaQuoteTimestamp": observed_at.isoformat(),
                "simulatedMarket": {
                    "enabled": True,
                    "fixture": "open_us_regular_session_v3",
                    "broker_orders_allowed": False,
                    "provider_calls_allowed": False,
                },
            }
        )
        quote_quality = classify_quote_quality(
            requested_exchange=exchange,
            provider_exchange=snapshot.get("exchange"),
            market_state="REGULAR",
            quote_timestamp=observed_at,
            observed_at=observed_at,
        )
        snapshot["quote_quality"] = quote_quality
        snapshot["quoteQualityStatus"] = quote_quality["status"]
        snapshot["alpacaQuoteAgeSeconds"] = quote_quality["quote_age_seconds"]
        snapshot["usMarketSession"] = quote_quality["market_session"]
        snapshot["usMarketOpen"] = quote_quality["market_open"]
        snapshot["valuation_metric_count"] = len(_CORE_VALUATION_KEYS)
        snapshot["valuation_data_complete"] = True
        snapshot["market_data_sources"] = ["simulated_market_smoke_v3"]
        snapshot["provider_status"] = {"simulated_market": "success"}
        snapshot["provider_errors"] = []
        snapshot["field_sources"] = {
            key: "simulated_market_smoke_v3"
            for key in snapshot
            if key
            not in {
                "symbol",
                "yf_symbol",
                "requested_exchange",
                "fetched_at",
                "simulatedMarket",
                "quote_quality",
                "provider_status",
                "provider_errors",
                "market_data_sources",
                "field_sources",
                "data_quality",
            }
        }
        snapshot["data_quality"] = _build_data_quality(snapshot)
        return snapshot

'''


def patch(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    if MARKER in text:
        raise RuntimeError(f"{MARKER} is already present")

    insertion = "    field_sources: Dict[str, str] = {}\n\n"
    if insertion not in text:
        raise RuntimeError("Scanner get_market_snapshot insertion point changed")

    path.write_text(text.replace(insertion, insertion + BLOCK, 1), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "path",
        nargs="?",
        default="../Scanner_Agent/app/data_sources/market_data.py",
    )
    args = parser.parse_args()
    target = Path(args.path)
    if not target.is_file():
        raise SystemExit(f"Scanner market_data.py not found: {target}")
    patch(target)
    print(f"Injected {MARKER} into {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

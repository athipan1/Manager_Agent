# Scanner Preselection Cache

The hourly workflow calls `/discover-analyze-trade` twice with identical Scanner discovery parameters:

1. `execute=false` selects candidates for exact Backtests.
2. `execute=true` continues through exposure, Backtest, Risk, and Execution gates.

`ScannerAgentClient` keeps the first successful broad-discovery response in a one-shot in-process cache. The second identical request reuses that response instead of scanning the full NASDAQ/S&P 500 universe again.

## Safety properties

- Cache keys include `max_universe`, `top_n`, `exchange`, and `max_workers`.
- Cache entries expire after `SCANNER_DISCOVERY_CACHE_TTL_SECONDS` (default: 1800 seconds).
- Each entry is consumed once, preventing later hourly or manual runs from inheriting the same response.
- The current request correlation ID replaces the original correlation ID.
- The exact Backtest execution gate remains authoritative, so Risk and Execution only receive symbols with fresh matching Backtest evidence.

## Diagnostics

A reused Scanner response includes the following metadata in both the top-level response and Scanner data metadata:

- `scanner_discovery_cache_hit`
- `scanner_discovery_cache_one_shot`
- `scanner_discovery_cache_age_seconds`
- `scanner_discovery_cache_ttl_seconds`
- `scanner_discovery_cache_key`

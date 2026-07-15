# Multi-Strategy Backtest Gate

The hourly Manager workflow now promotes Backtest evidence by exact selected strategy identity instead of assuming one fixed SMA strategy for every symbol.

## Hourly sequence

```text
Scanner preselection
  -> legacy fixed-strategy Backtest report retained for diagnostics
  -> exact-symbol multi-strategy selection
  -> publish only best_eligible strategy per symbol
  -> Database exact evidence lookup
  -> Manager Backtest gate
  -> Risk
  -> Execution
```

The existing workflow command remains stable. `scripts/verify_backtest_publish.py` invokes `scripts/run_multi_strategy_backtests.py` after the original Backtest report is created. The original report is preserved as `reports/hourly-backtest-fixed-strategy-result.json`, while `reports/hourly-backtest-result.json` becomes the authoritative multi-strategy selection report.

## Accepted strategy identities

The Manager gate accepts only the deterministic `balanced_v1` identities produced by Backtest_Agent:

- `sma-crossover-balanced-v1`
- `trend-following-balanced-v1`
- `mean-reversion-balanced-v1`
- `breakout-balanced-v1`

The legacy `hourly-sma-crossover` identity is deliberately excluded while multi-strategy gating is enabled. A passing legacy record therefore cannot authorize execution after a newer multi-strategy run finds no eligible strategy.

## Selection and publishing

Each Scanner-selected symbol is evaluated independently. Backtest_Agent returns `best_overall` for diagnostics and `best_eligible` for orchestration.

When `best_eligible` exists, Manager publishes one Database_Agent record using:

```text
skill_id    = BACKTEST_SKILL_ID
strategy_id = best_eligible.strategy_id
symbol      = exact symbol
 time frame = BACKTEST_TIMEFRAME
```

The publication metadata records the selection profile, score, gates, data fingerprint, bar count, and workflow run identity.

When no strategy passes every gate, the symbol receives `no_eligible_strategy`. This is a successful no-trade outcome:

- no Backtest record is published for that symbol
- no strategy ID is added to `strategy_ids_by_symbol`
- Manager's exact gate rejects the symbol
- Risk and Execution never receive it

## Failure semantics

The workflow fails closed when:

- Alpaca historical data cannot be fetched
- Backtest_Agent multi-strategy runtime is missing
- selection raises an operational error
- selected evidence cannot be published to Database_Agent
- the report claims an ineligible strategy was published
- the strategy map does not exactly match eligible symbols

A normal `no_eligible_strategy` result does not fail the workflow because refusing a weak trade is expected behavior.

## Default gates

The Manager runner uses the Backtest_Agent defaults unless environment variables override them:

```text
minimum trades             10
minimum annualized return   5%
minimum Sharpe ratio        0.80
minimum profit factor       1.20
maximum drawdown floor     -20%
minimum excess return       0%
maximum kill-switch events  0
```

## Configuration

```text
BACKTEST_MULTI_STRATEGY_ENABLED=true
BACKTEST_MULTI_STRATEGY_GATE_ENABLED=true
BACKTEST_GATE_STRATEGY_IDS=<comma-separated exact IDs>
BACKTEST_SELECTION_MIN_TRADES=10
BACKTEST_SELECTION_MIN_ANNUALIZED_RETURN=0.05
BACKTEST_SELECTION_MIN_SHARPE_RATIO=0.80
BACKTEST_SELECTION_MIN_PROFIT_FACTOR=1.20
BACKTEST_SELECTION_MAX_DRAWDOWN_FLOOR=-0.20
BACKTEST_SELECTION_MIN_EXCESS_RETURN=0.0
BACKTEST_SELECTION_MAX_KILL_SWITCH_EVENTS=0
```

Disabling multi-strategy execution or gating should be treated as a deliberate rollback and tested in Simulator mode before use.

# Hourly Alpaca Paper Portfolio Cycle

This workflow is a Paper-only automation boundary. It is not authorized to use
the Alpaca live endpoint or submit real-money orders.

## Audit summary before this change

- **P0:** the scheduled run used `DRY_RUN=true` and `BROKER_MODE=SIMULATOR`.
- **P0:** the scheduled stack started a local Database_Agent with SQLite dev
  mode instead of verifying and using the Railway Database_Agent.
- **P0:** Execution and Database API keys had development fallbacks and the
  workflow did not reject missing or placeholder secrets.
- **P0:** an absent Database/Broker sync status could pass the automation gate.
- **P1:** broker account, positions, orders, market clock, and existing
  protection were not reviewed as one required cycle before candidate entry.
- **P1:** order IDs were random, so a workflow rerun did not provide a durable
  Manager-to-Database idempotency identity.
- **P1:** Portfolio, Profit, Market Regime and the real Performance service were
  not all required by the scheduled runtime.
- **P2:** the concurrency group and report described generic simulator trading,
  rather than the hourly Paper portfolio boundary.

## Scheduled sequence

The cron is `5 * * * *` and concurrency is serialized with
`hourly-alpaca-paper-portfolio`.

1. Validate exact Paper flags and reject missing/placeholder credentials.
2. Verify Railway Database_Agent `/health`, `/ready`, and `/version`.
3. Verify the Alpaca Paper account and market clock directly.
4. Start the agents without local Database_Agent or PostgreSQL.
5. Reconcile account, positions and open orders to Railway and require parity.
6. Review every existing position with protection diagnostics, Technical,
   Fundamental, Market Regime, Portfolio, Profit and Performance context.
7. Cancel only stale non-protective orders and reconcile exact approved
   protective changes.
8. Run Scanner, exact-symbol Backtest, Portfolio/Risk gates and guarded Manager
   execution.
9. Reconcile again, verify fills/protection, store review history and upload the
   audit artifact.

When Alpaca reports a closed market, the cycle becomes
`PORTFOLIO_REVIEW_ONLY`; candidate analysis may run, but `execute=false` and no
new position can be opened.

## Automatic action boundary

Allowed after exact gates:

- `HOLD`
- `ADD_POSITION`
- `MOVE_STOP`
- `REPLACE_PROTECTION`
- `CANCEL_STALE_ORDER` for a fresh broker-identified non-protective order only

`PARTIAL_EXIT_RECOMMENDATION` and `EXIT_ALL_RECOMMENDATION` are persisted as an
order-review ticket with `execution_enabled=false`. The hourly Manager execution
path also rejects SELL decisions before creating an order.

## Required GitHub secrets

- `ALPACA_API_KEY_ID`
- `ALPACA_SECRET_KEY`
- `ALPACA_API_URL` — exactly `https://paper-api.alpaca.markets`
- `EXECUTION_API_KEY`
- `DATABASE_AGENT_URL` — the HTTPS Railway Database_Agent service URL
- `DATABASE_AGENT_API_KEY`
- `RISK_ADMIN_TOKEN`
- `PORTFOLIO_AGENT_API_KEY`

SMTP secrets are optional; the uploaded artifact remains authoritative when
email is not configured. Secret values must never be printed in workflow logs.

## Idempotency and reconciliation

`portfolio_cycle_id` is deterministic for the Paper account and UTC hour:

`hourly-paper-{account_hash}-{YYYYMMDDTHH}`

Each order derives a key from the cycle, account, symbol, side, strategy and
position lifecycle. Manager asks Railway Database_Agent for that trade ID before
persisting another approval or calling Execution. Pending BUY orders are still
included by the existing exposure gate. Missing or mismatched broker sync blocks
new execution.

## Validation and first-run procedure

Before opening the PR:

```bash
python -m compileall .
pytest -q
docker compose -f docker-compose.yml -f docker-compose.risk.yml \
  -f docker-compose.alpha.yml -f docker-compose.hourly-paper.yml config
```

After an explicitly authorized merge, first dispatch with `dry_run=true` and
`broker_mode=SIMULATOR`. Inspect all artifacts. Then dispatch with
`dry_run=false`, `broker_mode=ALPACA`; the runtime remains locked to
`TRADING_MODE=PAPER` and `ALLOW_LIVE_TRADING=false`. Do not rely on the hourly
schedule until both manual checks pass.

## Rollback

Disable the schedule or revert this PR. Do not restore the previous scheduled
Simulator workflow as an execution mechanism. Existing Alpaca Paper positions
and protective orders remain broker-side; review them manually after rollback.
No Railway PostgreSQL resource is created or deleted by this change.

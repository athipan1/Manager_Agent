# Full-System Backtest Promotion E2E

This workflow proves the paper-only authority chain across the production source of five repositories:

`Backtest_Agent -> Database_Agent promotion -> Manager_Agent approval -> Risk_Agent -> Execution_Agent simulator`

## What is real

- PostgreSQL 13 is the authoritative database.
- Database_Agent runs its real API and promotion repository.
- Backtest_Agent runs its real HTTP client and promotion lifecycle module in a separate Python process.
- Manager_Agent runs its real promotion execution gate and privileged approval adapter.
- Risk_Agent runs its real manager decision gate API.
- Execution_Agent runs its real API and deterministic Simulator broker adapter.
- Database risk approvals, orders, promotion history, and exact lookup are read back through real APIs.

The only external component replaced is the trading broker. `BROKER_MODE=SIMULATOR`, `TRADING_MODE=PAPER`, and `ALLOW_LIVE_TRADING=false` are validated before the stack starts.

## Scenarios

1. Store immutable nested/statistical/robustness Backtest evidence.
2. Backtest_Agent advances only to `ROBUSTNESS_PASSED`.
3. Manager_Agent performs the privileged transition to `APPROVED_FOR_PAPER`.
4. Risk_Agent approves the exact Manager decision and strategy.
5. Database_Agent stores the risk approval with the original correlation ID.
6. Execution_Agent accepts the simulator order only with the risk approval.
7. The identical idempotency key is submitted twice and must resolve to one order ID.
8. Promotion history must contain exactly four transitions and one correlation ID.
9. A newer exact promotion is moved to `FAILED`; Manager must block it instead of falling back to the older approved promotion.
10. Replaying the original Backtest lifecycle must not create extra transitions or mutate downstream approval state.

## Evidence artifacts

The workflow retains:

- immutable repository revisions
- rendered compose configuration
- compose build/start log
- lifecycle JSON report
- PostgreSQL, Database, Risk, and Execution logs
- final compose service state

## Safety assertions

- Backtest_Agent stops at version 4, `ROBUSTNESS_PASSED`.
- Manager decision says `requires_risk_approval=true`.
- Manager decision says `broker_boundary=execution-agent-only`.
- Risk approval exists before the Execution request.
- The order preserves the originating correlation ID.
- Duplicate requests return the same order ID.
- Newer failed evidence blocks older approved evidence.

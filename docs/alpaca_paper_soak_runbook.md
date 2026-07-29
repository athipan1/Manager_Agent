# Alpaca Paper validation and soak runbook

This runbook promotes the Simulator-tested portfolio cycle to Alpaca Paper
without enabling scheduled Profit lifecycle execution.

## Safety invariants

- `TRADING_MODE=PAPER`, `BROKER_MODE=ALPACA`, and `DRY_RUN=false`.
- `ALPACA_API_URL` must exactly equal `https://paper-api.alpaca.markets`.
- `ALLOW_LIVE_TRADING=false`.
- `PROFIT_DECISION_EXECUTION_ENABLED=false`.
- `PROFIT_AUTO_EXIT_ALL_ENABLED=false`.
- Broker/Database reconciliation is required before analysis, before execution,
  and after execution.
- Existing positions must have exact, non-duplicate protective quantities.
- A durable emergency-halt issue blocks every new Paper cycle and is checked
  again immediately before the Manager execution phase.

The halt deliberately does not cancel a cycle that has already submitted an
order. That cycle is allowed to finish reconciliation and protection checks;
future broker mutations remain blocked.

## 1. Manual broker validation

Run **Manual Alpaca Paper Trading** from `main`.

- `confirmation`: `EXECUTE_ALPACA_PAPER`
- Keep the default Scanner limits for the first run.
- Confirm `HOURLY_PAPER_SCHEDULE_ENABLED` is not `true`.

The workflow:

1. checks the durable emergency halt;
2. validates the Paper account, Railway Database and market clock;
3. trips the runtime Risk halt, verifies a Paper risk probe is rejected, clears
   the halt, and verifies readiness recovers;
4. reviews and reconciles broker positions/orders;
5. runs the existing guarded hourly cycle;
6. verifies post-cycle reconciliation and protection;
7. stores 90-day audit evidence.

A failed manual cycle opens the operator alert issue and automatically activates
the durable Alpaca Paper emergency halt.

## 2. Start a 24–72 hour soak

Run **Alpaca Paper Soak** from `main`.

- `operation`: `start`
- `duration_hours`: `24`, `48`, or `72`
- `confirmation`: `START_ALPACA_PAPER_SOAK`

The workflow creates one durable control issue. Its scheduled trigger runs at
minute 17 of each hour while the issue is active. Do not enable the normal
scheduled hourly workflow during the soak.

Use `operation=status` to inspect counts. To stop early, run:

- `operation`: `stop`
- `confirmation`: `STOP_ALPACA_PAPER_SOAK`

Each cycle records success, warning, or failure in the control issue. A failure
closes the soak and activates the durable halt. A partial fill is a warning and
blocks promotion until manually reviewed.

## 3. Emergency halt

Run **Alpaca Paper Emergency Halt**:

- Activate: `operation=activate`, provide a reason, and enter
  `HALT_ALPACA_PAPER`.
- Inspect: `operation=status`.
- Clear only after broker, Database, open-order and protection checks are clean:
  `operation=clear`, provide the verification reason, and enter
  `CLEAR_ALPACA_PAPER_HALT`.

The halt workflow does not need broker credentials. Its issue-backed state
survives runner teardown and is enforced by later manual, soak and hourly runs.

## Promotion gate for scheduled Profit lifecycle

Do not enable scheduled Profit lifecycle execution unless the closed soak issue
has all of the following:

- `promotion_ready=true`;
- elapsed duration of at least 24 hours;
- at least one clean hourly cycle for every requested soak hour;
- zero failed cycles;
- zero warning cycles requiring review;
- zero unresolved broker/Database mismatches;
- zero unprotected or quantity-mismatched positions;
- every emergency-halt drill passed and restored readiness;
- no open durable emergency-halt or operator-alert issue.

Promotion is a separate change and review. The soak workflows never modify the
scheduled production flag or enable automatic Profit exits.

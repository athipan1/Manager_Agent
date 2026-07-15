# Walk-Forward Backtest Execution Gate

The hourly Manager workflow requires rolling out-of-sample evidence before a Scanner-selected symbol may reach Risk or Execution.

## Dependency

This integration depends on Backtest_Agent PR #21 and its endpoint:

```text
POST /backtest/multi-strategy/walk-forward
```

Backtest_Agent PR #21 must be merged before this Manager change is enabled in the hourly workflow.

## Hourly flow

```text
Scanner preselection
  -> start or discover Backtest_Agent API
  -> POST exact symbol and historical bars
  -> full-period multi-strategy comparison
  -> rolling out-of-sample validation
  -> publish only best_eligible strategy and stability evidence
  -> Database exact lookup
  -> Manager evidence validation
  -> Risk
  -> Execution
```

The workflow keeps the original fixed-strategy report as diagnostics. The authoritative report mode becomes:

```text
walk_forward_multi_strategy_selection
```

## HTTP execution

Manager no longer calls the multi-strategy selection function directly. It sends the request through the Backtest_Agent API contract.

In GitHub Actions, `scripts/local_backtest_api.py` starts a temporary localhost Backtest_Agent process from the checked-out repository when no service is already reachable. The process is terminated after validation. A deployed environment may provide an existing `BACKTEST_AGENT_URL` and disable local autostart.

## Database evidence

Only a strategy returned as `best_eligible` is published. The run retains the exact identity:

```text
skill_id + strategy_id + symbol + timeframe
```

Its metadata includes:

- `validation_profile=rolling_walk_forward_v1`
- `walk_forward_required=true`
- `walk_forward_passed`
- `walk_forward_status`
- stability score
- completed window count
- profitable-window rate
- median Sharpe ratio
- median profit factor
- worst out-of-sample drawdown
- all walk-forward gates
- complete window-level validation evidence
- walk-forward criteria
- dataset fingerprint and workflow identity

The deterministic run ID includes both the exact strategy configuration and walk-forward criteria. Changing the minimum windows or another stability threshold therefore creates a distinct evidence identity.

## Manager gate

When `BACKTEST_WALK_FORWARD_GATE_REQUIRED=true`, Manager rejects evidence unless all conditions hold:

1. the exact symbol, strategy, skill, and timeframe match
2. the run is completed and fresh
3. Database_Agent marks the skill result as passed
4. `validation_profile` is `rolling_walk_forward_v1`
5. both the top-level metadata and nested validation mark Walk-forward as passed
6. validation status is `completed`
7. every persisted selection and Walk-forward gate is true
8. evaluated windows meet the persisted minimum

Legacy full-period-only records cannot authorize execution after this gate is enabled.

## Failure semantics

A normal `no_eligible_strategy` result is a successful no-trade decision. Nothing is published and the symbol cannot reach Risk.

The workflow fails when:

- Backtest_Agent cannot start or is unreachable
- the Walk-forward endpoint returns an error
- the response violates the expected schema
- an eligible selection lacks passing stability evidence
- Database publication fails
- the published metadata does not match the selection evidence

Database HTTP 404 is classified as `backtest_not_found`. Timeouts, connection failures, and server errors remain `backtest_lookup_failed`.

## Configuration

```text
BACKTEST_WALK_FORWARD_ENABLED=true
BACKTEST_WALK_FORWARD_GATE_REQUIRED=true
BACKTEST_AGENT_URL=http://localhost:8016
BACKTEST_AGENT_AUTOSTART_LOCAL=true
BACKTEST_WALK_FORWARD_TIMEOUT_SECONDS=900
BACKTEST_WALK_FORWARD_TRAIN_BARS=126
BACKTEST_WALK_FORWARD_TEST_BARS=126
BACKTEST_WALK_FORWARD_STEP_BARS=63
BACKTEST_WALK_FORWARD_MIN_WINDOWS=4
BACKTEST_WALK_FORWARD_MIN_WINDOW_TRADES=1
BACKTEST_WALK_FORWARD_MIN_PROFITABLE_RATE=0.60
BACKTEST_WALK_FORWARD_MIN_MEDIAN_SHARPE=0.70
BACKTEST_WALK_FORWARD_MIN_MEDIAN_PROFIT_FACTOR=1.10
BACKTEST_WALK_FORWARD_MAX_DRAWDOWN_FLOOR=-0.20
BACKTEST_WALK_FORWARD_MAX_KILL_SWITCH_EVENTS=0
```

Disabling the Walk-forward gate is a rollback action and should remain limited to Simulator testing.

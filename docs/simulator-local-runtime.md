# Manual Simulator Local Runtime

Manual `workflow_dispatch` runs with `dry_run=true` and
`broker_mode=SIMULATOR` use the local `Database_Agent` with SQLite. They do not
require Railway availability or Railway credentials.

The workflow creates independent, high-entropy API credentials for
`Manager_Agent`, `Database_Agent`, `Execution_Agent`, `Portfolio_Agent`, and the
Risk admin boundary. These credentials are written only to the current GitHub
Actions job through `GITHUB_ENV`; their values are never printed and disappear
when the runner is destroyed.

The helper refuses to run when any of these boundaries are not exact:

- `GITHUB_EVENT_NAME` is not `schedule`
- `TRADING_MODE=PAPER`
- `BROKER_MODE=SIMULATOR`
- `DRY_RUN=true`
- `ALLOW_LIVE_TRADING=false`

Scheduled and manual Alpaca Paper runs remain unchanged. They still require the
real GitHub Secrets, the Railway `Database_Agent`, strict broker reconciliation,
and the exact Alpaca Paper endpoint.

# Public dashboard snapshot

`Manager_Agent` remains an ephemeral GitHub Actions workload. The React dashboard does not call a running Manager container.

Data path:

```text
Hourly Auto Trading
  -> hourly-auto-trading-report artifact
  -> Publish Dashboard Snapshot workflow
  -> allowlisted dashboard-snapshot.v2
  -> dashboard-data branch
  -> Trading_Frontend polling over HTTPS
```

The public URL is:

```text
https://raw.githubusercontent.com/athipan1/Manager_Agent/dashboard-data/docs/dashboard/latest-dashboard-snapshot.json
```

The `dashboard-data` branch is intentionally separate from `main`. Hourly snapshot commits therefore do not trigger source CI, do not create merge pressure on application code, and can be rebased and pushed with bounded retries without force-push.

## Privacy

`DASHBOARD_SNAPSHOT_PRIVACY_MODE` supports:

- `full`: allowlisted account and position values are included.
- `masked`: default for this public repository; financial values are null while status and counts remain visible.
- `status-only`: positions, orders, and signals are omitted.

The exporter builds a new object from an allowlist. It never copies the hourly report wholesale. Order identifiers, client order identifiers, credentials, authorization headers, environment variables, private service URLs, stack traces, and raw exceptions are excluded.

## Failure behavior

The publish workflow runs for every completed Hourly Auto Trading conclusion. When the artifact is unavailable or malformed, it publishes a restricted fallback from GitHub `workflow_run` metadata. A failed latest run remains visible while `lastSuccessfulRun` is preserved from the previous snapshot.

Publishing is a separate workflow, so a snapshot download, validation, commit, or push failure cannot change the result of the Hourly Auto Trading run.

## Safety invariants

This data pipeline does not modify the trading runtime. Hourly trading remains Paper-only with:

```text
ALLOW_LIVE_TRADING=false
PROFIT_DECISION_EXECUTION_ENABLED=false
PROFIT_AUTO_EXIT_ALL_ENABLED=false
```

# Curator advisory soak

The `Curator Advisory Soak` workflow repeatedly exercises the signed Curator API → Sandbox Worker → hardened skill-container path without starting Manager trading, Execution_Agent, Risk_Agent, Scanner_Agent or Alpaca.

## Safety model

Each run:

- creates ephemeral execute, admin, worker and Database credentials;
- starts only the Curator dependency chain and telemetry Database_Agent;
- confirms the Curator API has no Docker CLI or socket;
- confirms only the private worker owns Docker-daemon access;
- registers one deterministic advisory-only skill;
- executes the same input repeatedly through the remote worker;
- requires identical output on every cycle;
- rejects fallback, broker/order fields, network access or writable sandbox roots;
- verifies that the shared host workspace is empty after execution;
- uploads a JSON evidence report for 14 days.

The workflow does not read Alpaca credentials and cannot submit orders.

## Manual validation

Open GitHub Actions in `athipan1/Manager_Agent`, select `Curator Advisory Soak`, and choose `Run workflow`.

Recommended first run:

```text
cycles: 12
symbol: TEST
```

The report is uploaded as:

```text
curator-advisory-soak-<run-id>-<attempt>
```

A successful report has:

```json
{
  "status": "success",
  "advisory_only": true,
  "cycles_requested": 12,
  "cycles_completed": 12,
  "fallback_count": 0,
  "unique_output_hashes": ["one deterministic hash"]
}
```

## Hourly 24–72 hour soak

The hourly cron is fail-safe disabled unless this Repository Variable is set:

```text
CURATOR_ADVISORY_SOAK_ENABLED=true
```

Configure it in:

```text
Manager_Agent
→ Settings
→ Secrets and variables
→ Actions
→ Variables
→ New repository variable
```

Leave the variable absent or set it to `false` to disable scheduled runs.

For a 24-hour soak, enable the variable and inspect 24 consecutive hourly artifacts. For a 72-hour soak, inspect 72 consecutive artifacts. Every successful run must show:

- `fallback_count = 0`;
- one unique output hash;
- secure remote-worker readiness before and after execution;
- no workspace residue;
- no failed or incomplete cycles.

## Promotion criteria

Do not enable Curator in `docker-compose.hourly-paper.yml` until the selected soak window completes without:

- readiness failures;
- worker restarts during execution;
- process fallback;
- nondeterministic output;
- duplicate or forbidden order identifiers;
- workspace residue;
- missing evidence artifacts.

Even after promotion, Curator remains advisory-only. Risk_Agent remains mandatory, and Execution_Agent remains the only order-submission path.

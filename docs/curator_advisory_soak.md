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
- requires every execution to persist a Database telemetry record with correlation ID;
- rejects fallback, broker/order fields, network access or writable sandbox roots;
- verifies that the shared host workspace is empty after execution;
- uploads a JSON evidence report for 14 days.

The workflow does not read Alpaca credentials and cannot submit orders.

## Defects discovered during the initial soak

The first real soak found that Curator's performance layer appended calibration fields after the skill output had already passed schema validation. That made the returned output conflict with `additionalProperties=false` while the schema status still reported valid.

Curator_Agent PR #21 fixed the executor contract in merge commit `c4286bbab9abe529b2ded7e8266e5be9fe5221ce`:

- schema-validated skill output is now immutable;
- raw and calibrated confidence remain in advisory performance metadata;
- `effective_confidence` is exposed outside the skill-defined output;
- deterministic output and schema truthfulness are preserved.

The same soak then exposed HTTP 500 responses from Database skill-performance persistence. `create_skill_execution_log()` passed `symbol` twice, and `create_skill_trade_outcome()` passed `symbol` and `closed_at` twice. Database_Agent PR #117 fixed both constructors in merge commit `a2d1b75b77b42f9fc381daab73bb4c7522672578` and added PostgreSQL-backed CI plus focused repository regression tests.

The soak must run against these commits or later `main` revisions. A cycle now fails unless Database telemetry returns `status=success`, preserves a correlation ID and returns a real `execution_log_id`.

## Readiness versus execution evidence

The worker readiness contract proves that the Docker daemon is reachable, the configured sandbox image exists, secure container execution is available, and the required shared work root is configured. Network isolation and read-only root filesystem flags are execution-result properties, so the soak verifies them on every real skill execution rather than expecting them from `/ready`.

This separation prevents an optimistic readiness response from substituting for actual sandbox evidence.

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

Every cycle must also contain:

```json
{
  "database_telemetry": {
    "status": "success",
    "correlation_id": "present",
    "execution_log_id": "present"
  }
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
- successful Database telemetry on every cycle;
- secure remote-worker readiness before and after execution;
- no workspace residue;
- no failed or incomplete cycles.

## Promotion criteria

Do not enable Curator in `docker-compose.hourly-paper.yml` until the selected soak window completes without:

- readiness failures;
- worker restarts during execution;
- process fallback;
- telemetry persistence failures;
- nondeterministic output;
- duplicate or forbidden order identifiers;
- workspace residue;
- missing evidence artifacts.

Even after promotion, Curator remains advisory-only. Risk_Agent remains mandatory, and Execution_Agent remains the only order-submission path.

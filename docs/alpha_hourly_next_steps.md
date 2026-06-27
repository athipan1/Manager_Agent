# Alpha Advisory Hourly Rollout

## Current hourly report observation

The hourly auto-trading workflow is running the main stack with Risk and Curator overlays, but it does not yet run the alpha advisory agents:

- Market_Regime_Agent
- Portfolio_Agent
- Profit_Agent
- Performance_Agent

The latest report also shows:

- Database/Broker sync is OK
- Positions exist for ACGL and ADBE
- Open orders exist for CINF, ACGL, and ADBE
- ACGL and ADBE are still stored as `strategy_bucket = unassigned` in Database context
- No new execution candidates were submitted because selected positions already have protected open broker orders

## Safe rollout plan

### Phase 1: Smoke test alpha agents

Use the new `Alpha Advisory Smoke Test` workflow.

This workflow:

- Builds the four alpha agents
- Starts them as isolated containers
- Calls their health endpoints
- Calls their advisory endpoints with mock payloads
- Does not start Manager's trading flow
- Does not send any broker orders

### Phase 2: Add alpha data to hourly report

After the smoke workflow is green, update the hourly auto-trading workflow to:

1. Checkout the four alpha agent repos
2. Include `docker-compose.alpha.yml`
3. Set `ALPHA_AGENTS_ENABLED=true`
4. Call `/alpha/health`
5. Call `/alpha/advisory`
6. Render an Alpha Advisory section in `hourly-auto-trading-report.md`

### Phase 3: Fix strategy bucket persistence

Before using Portfolio_Agent for real trading decisions, persist strategy buckets from the selected candidate metadata into Database positions/orders.

Current problem:

```text
ACGL -> selected as value_rebound, but DB position remains unassigned
ADBE -> selected as core_dividend, but DB position remains unassigned
```

Expected fix:

```text
ACGL -> value_rebound
ADBE -> core_dividend
```

### Phase 4: Use alpha outputs as gates

Only after Phase 1-3 are stable:

- Market_Regime_Agent can reduce aggressiveness in volatile/bear markets
- Portfolio_Agent can block new buys when buckets are over target
- Profit_Agent can recommend partial exit or stop movement
- Performance_Agent can feed Learning_Agent/reporting

## Safety rule

Alpha agents must remain advisory-only. They should never call Execution_Agent directly.

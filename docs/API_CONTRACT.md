# Multi-Agent Trading API Contract

This document defines the baseline API contract for service-to-service communication in the multi-agent trading system.

The goal is to make every agent predictable, traceable, and safe to orchestrate from `Manager_Agent`.

## Standard Headers

Every agent-to-agent request must include:

```http
Content-Type: application/json
X-Correlation-ID: <uuid>
X-API-KEY: <agent-api-key>
```

### Header Rules

- `X-Correlation-ID` must be created by `Manager_Agent` at the beginning of each workflow and forwarded to all downstream agents.
- `X-API-KEY` must be used for protected internal endpoints.
- Public operational endpoints may omit API keys only when explicitly documented, for example `/health`, `/ready`, and `/version`.

## Required Operational Endpoints

Every agent should expose these endpoints:

```http
GET /health
GET /ready
GET /version
```

| Endpoint | Purpose |
| --- | --- |
| `/health` | Confirms that the process is alive and basic dependencies can be checked. |
| `/ready` | Confirms that the service is configured and ready to accept real workflow traffic. |
| `/version` | Returns agent version, schema version, and contract metadata. |

## Standard Response

Every agent should return this response envelope:

```json
{
  "status": "success",
  "agent_type": "manager-agent",
  "version": "1.0.0",
  "schema_version": "1.0",
  "timestamp": "2026-07-04T00:00:00Z",
  "correlation_id": "00000000-0000-0000-0000-000000000000",
  "data": {},
  "metadata": {},
  "error": null
}
```

### Required Fields

| Field | Type | Notes |
| --- | --- | --- |
| `status` | `success` or `error` | Top-level request result. |
| `agent_type` | string | Stable agent identifier, for example `technical`, `risk`, or `manager-agent`. |
| `version` | semantic version string | Agent implementation version. |
| `schema_version` | semantic version string | API contract schema version. |
| `timestamp` | ISO-8601 datetime | Response creation time, preferably UTC. |
| `correlation_id` | string or null | Workflow trace ID. New internal calls should always include it. |
| `data` | object, array, scalar, or null | Successful payload. |
| `metadata` | object | Non-critical diagnostics, runtime mode, feature flags, or warnings. |
| `error` | object or null | Error payload when `status=error`. |

## Standard Error Response

```json
{
  "status": "error",
  "agent_type": "manager-agent",
  "version": "1.0.0",
  "schema_version": "1.0",
  "timestamp": "2026-07-04T00:00:00Z",
  "correlation_id": "00000000-0000-0000-0000-000000000000",
  "data": null,
  "metadata": {},
  "error": {
    "code": "AGENT_UNAVAILABLE",
    "message": "Target agent is unavailable",
    "retryable": true
  }
}
```

## Orchestration Rules

1. `Manager_Agent` is the only service allowed to orchestrate trade execution.
2. Alpha-layer agents are advisory-only and must not submit orders directly.
3. `Risk_Agent` must approve trade plans before `Execution_Agent` receives an executable order.
4. `Execution_Agent` must never run live execution unless live trading is explicitly enabled by configuration.
5. Every trade decision must be traceable with `correlation_id`.
6. Every trade action must be auditable in `Database_Agent`.
7. Mock/dev fallback behavior is forbidden in `LIVE` mode.
8. Backtest and performance gates should validate strategy or policy changes before promotion.

## Profit decision orchestration contract

Manager reads the Database-owned lifecycle, forwards it to Profit_Agent, and
requires a deterministic advisory `decision_id` before any exit execution.
Legacy Profit responses without lifecycle identity remain readable during
migration but are blocked from automatic execution.

Manager reserves the decision through Database_Agent before Risk submission,
persists `RISK_APPROVED` before execution, and persists `EXECUTION_PENDING`
before calling Execution_Agent. The same `decision_id` is used as the execution
`trade_id` and `Idempotency-Key`. A retry first reads both the decision record
and the Database order record, so an accepted order is not submitted twice.

Only a broker-confirmed filled/executed order advances the decision to
`EXECUTED` and applies target lifecycle changes. Rejections are terminal;
timeouts and ambiguous server errors stay `EXECUTION_PENDING` for safe
reconciliation. Manager carries one correlation ID through Database, Risk, and
Execution calls.

The PR2 implementation supports whole-share exits in PAPER/SIMULATOR only.
Fractional quantities and market increments are intentionally deferred to the
Decimal/tick-size contract. `exit_all` remains blocked by default.

## Authenticated Profit Agent contract

Manager sends `X-API-KEY` from `PROFIT_AGENT_API_KEY` and the current
`X-Correlation-ID` to Profit Agent. The same correlation ID continues through
Database decision reservation/transitions, Risk, and Execution. Keys are never
written to reports, logs, request metadata, or response bodies.

Manager accepts both numeric legacy schema versions and named versions such as
`profit-decision.v2`. A mismatched response correlation ID fails closed. A
legacy Profit response without `profit-decision.v2` is allowed only for the
temporary advisory migration path and emits a deprecation warning. It remains
ineligible for automatic execution without deterministic lifecycle identity.

For adaptive profit review, Manager consumes only
`profit-market-context.v1` and `profit-technical-context.v1` projections. It
forwards available evidence without inventing missing ATR, trend, volume, or
event fields and attaches Database-owned peak/version quality. Evidence older
than `PROFIT_MARKET_DATA_MAX_AGE_SECONDS` is marked stale; Profit then returns a
blocked review rather than an execution recommendation. Hard stop and base
trailing breaches retain priority inside Profit_Agent.

Compatibility timeline:

- `profit-decision.v2` is current from 2026-07-22.
- `profit-plan.v1`/missing request schema remains readable through the announced
  migration target of 2026-10-31.
- Removing legacy support requires a separate breaking-change release and will
  not happen silently.

## Manager_Agent Baseline

`Manager_Agent` now exposes the required operational endpoint set:

```http
GET /health
GET /ready
GET /version
```

These endpoints are the first contract anchor for rolling the same standard across the remaining agents.

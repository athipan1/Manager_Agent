# Pre-risk capacity-aware portfolio selection

Manager_Agent applies `manager-pre-risk-capacity-v1` after classification and
bucket selection, but before a BUY candidate is sent to Risk_Agent.

Risk_Agent remains authoritative. This Manager gate only removes or resizes
candidates that are already impossible under the shared stock exposure limits.

## Root cause addressed

The portfolio allocation response previously used the whole bucket target as a
single symbol's `target_value`.

For a portfolio worth about $150,813:

```text
value_rebound bucket target = 30% = about $45,244
value_rebound symbol cap    =  7% = about $10,557
```

Sending `$45,244` as ADBE's final target caused Risk_Agent to project the symbol
to the full bucket target, even though ADBE already had exposure above the
per-symbol limit.

The contract now separates:

```text
bucket_target_value  = total target for the complete strategy bucket
target_value         = final target for one symbol
```

`target_value` is always capped to the smallest applicable per-symbol target.

## Capacity checks

For each classified BUY candidate, Manager computes:

- current symbol exposure
- current strategy-bucket exposure
- current sector exposure, when sector data exists
- remaining symbol capacity
- remaining bucket capacity
- remaining sector capacity
- desired final symbol target
- allowed incremental BUY value

The stable default limits mirror Risk_Agent environment variables:

```text
MAX_SINGLE_STOCK_PCT             0.10
MAX_SECTOR_EXPOSURE_PCT          0.25
MAX_CORE_DIVIDEND_BUCKET_PCT     0.50
MAX_VALUE_REBOUND_BUCKET_PCT     0.30
MAX_NEWS_MOMENTUM_BUCKET_PCT     0.20
MAX_CORE_DIVIDEND_SYMBOL_PCT     0.10
MAX_VALUE_REBOUND_SYMBOL_PCT     0.07
MAX_NEWS_MOMENTUM_SYMBOL_PCT     0.03
```

Risk_Agent repeats these checks independently before approving an order.

## Selection outcomes

A candidate can be:

### Accepted without resize

The requested final target fits all known capacities.

### Accepted with resize

Manager reduces the final symbol target to the smallest remaining capacity. For
example, if a Value position currently has $5,000 exposure and its cap is
$7,000, Manager sends a final target of `$7,000`, representing a `$2,000`
increment.

### Skipped before Risk

Examples:

```text
current_symbol_exposure_at_or_above_limit
per_symbol_target_already_met
bucket_capacity_exhausted
sector_capacity_exhausted
remaining_capacity_below_minimum_trade_value
```

Skipped candidates remain visible in `bucket_selection.<bucket>.capacity_skipped`
with the full calculation and policy version.

### Overflow candidate promoted

When a selected candidate is blocked, the next eligible candidate from the same
bucket's overflow list is evaluated. It is promoted only if it fits the same
symbol, bucket and sector limits.

## Request-local position state

The discovery workflow already computes total position exposure immediately
before building allocation. That function stores an immutable position snapshot
in a Python `ContextVar`.

This provides:

- no process-wide mutable portfolio state
- no ticker-specific rules
- no cross-request leakage
- the same position rows for portfolio value and capacity calculations

## Output fields

Selected positions and Risk payloads now include:

```text
bucket_target_value
capacity_adjusted_target_value
capacity_incremental_value
capacity_policy_version
capacity_fallback_promoted
pre_risk_capacity
```

The bucket-selection summary includes pre-capacity and post-capacity counts,
skips and fallback promotions.

## Safety

This feature does not approve orders. The full guarded invariant remains:

```text
Manager classified bucket
== Risk approved bucket
== Execution requested bucket
== Database persisted bucket
== report bucket
```

True evidence conflicts remain fail-closed, and every accepted BUY still
requires Risk_Agent approval.

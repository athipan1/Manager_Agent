# Strategy Bucket Classification Contract

Manager_Agent is the final authority for assigning a candidate to one of the controlled strategy buckets:

- `core_dividend`
- `value_rebound`
- `news_momentum`
- `unassigned`

## Classification output

Every ranked candidate receives:

- `strategy_bucket`
- `bucket_confidence`
- `bucket_classification_status`
- `bucket_classification_reasons`
- `bucket_classifier_version`
- `strategy_bucket_classification`

Current classifier version:

```text
manager-strategy-bucket-v2
```

## Gate policy

```text
confidence >= 0.70  -> classified; eligible to continue toward Risk
0.50 - 0.69        -> review; strategy_bucket=unassigned; no new BUY
confidence < 0.50  -> unassigned; no new BUY
conflicting signals -> conflict; strategy_bucket=unassigned; no new BUY
invalid Scanner hint -> invalid; strategy_bucket=unassigned; no new BUY
```

A high opportunity score does not bypass the classification gate.

Risk-reducing SELL orders remain permitted with `unassigned` so unresolved historical attribution cannot prevent an exit.

## Scanner contract

Scanner hints are evidence, not final authority. Unknown Scanner bucket names are rejected rather than converted to a known bucket. Strong conflicting evidence is quarantined instead of selecting an arbitrary winner.

## Held positions

There are no ticker-specific bucket assignments in source code. Database_Agent history remains the source of truth for existing holdings.

A temporary operator migration can be supplied explicitly through:

```text
MANAGER_POSITION_BUCKET_OVERRIDES_JSON
```

Example:

```json
{"LEGACY_SYMBOL":"core_dividend"}
```

These overrides are lower priority than a valid bucket already stored in Database_Agent and must not be used as a permanent classification mechanism.

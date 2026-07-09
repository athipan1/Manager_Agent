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
- `evidence_gate_passed`
- `evidence_summary`
- `evidence_versions`
- `evidence_statuses`
- `source_conflicts`

Current classifier version:

```text
manager-strategy-bucket-v3
```

Manager evidence adapter version:

```text
manager-analysis-evidence-v1
```

## Supported child-agent contracts

```text
scanner-bucket-hints-v2
fundamental-evidence-v1
technical-evidence-v1
```

Scanner hints are non-binding. Fundamental_Agent and Technical_Agent must not assign a strategy bucket. Both must report:

```text
strategy_bucket_hint = null
bucket_decision_authority = manager
manager_decision_required = true
```

## Evidence gate

Manager remains backward-compatible with fully legacy payloads. Once any supported versioned evidence contract is present, all three versioned sources are required.

A new BUY is quarantined when any of these conditions is true:

- a versioned source is missing
- an evidence version is unsupported
- Fundamental or Technical evidence is `insufficient`
- a child agent claims final bucket authority
- a child agent emits a final strategy bucket
- Scanner marks its hint as binding
- Scanner reports an internal bucket conflict
- a child-agent response is not successful

Partial evidence is allowed but its contribution is discounted.

## Classification confidence policy

```text
confidence >= 0.70   -> classified; eligible to continue toward Risk
0.50 - 0.69          -> review; strategy_bucket=unassigned; no new BUY
confidence < 0.50    -> unassigned; no new BUY
conflicting signals  -> conflict; strategy_bucket=unassigned; no new BUY
invalid contract     -> invalid; strategy_bucket=unassigned; no new BUY
failed evidence gate -> evidence_insufficient; no new BUY
```

A high opportunity score does not bypass either the evidence gate or the bucket-classification gate.

Risk-reducing SELL orders remain permitted with `unassigned` so unresolved historical attribution cannot prevent an exit.

## Scanner contract

Scanner hints are evidence, not final authority. For versioned Scanner hints, Manager caps Scanner-only confidence below the auto-classification threshold. Fundamental or Technical evidence must corroborate the bucket before a new BUY can be auto-classified.

Unknown Scanner bucket names are rejected rather than converted to a known bucket.

## Fundamental evidence

Manager reads normalized `0–1` fields from `fundamental_evidence.raw_scores` and `fundamental_evidence.metrics`, including:

- quality and valuation scores
- growth score
- PE and PB
- free cash flow
- debt-to-equity
- dividend yield
- sector

Legacy `0–100` scores remain supported and are normalized before comparison.

## Technical evidence

Manager reads:

- technical score
- momentum score
- trend score
- indicator score
- technical vote score
- breakout ratio
- walk-forward validation provenance

A failed walk-forward result discounts Technical evidence before classification.

## Risk payload audit context

Selected positions forwarded to Risk include:

- `evidence_summary`
- `evidence_versions`
- `fundamental_evidence_status`
- `technical_evidence_status`
- `source_conflicts`
- `classification_inputs`

This records the exact normalized evidence used by Manager.

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

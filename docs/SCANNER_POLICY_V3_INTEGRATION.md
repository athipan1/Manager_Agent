# Manager integration for Scanner bucket-hint policy v3

Manager_Agent remains the final authority for strategy-bucket classification.
Scanner_Agent supplies typed, non-binding evidence through:

```text
contract: scanner-bucket-hints-v2
policy:   scanner-bucket-hint-policy-v3
```

## Runtime policy

Manager applies `manager-scanner-policy-v1` only when both the Scanner contract
and policy versions are explicitly present. Legacy Scanner payloads continue to
use the existing classifier unchanged.

### Suggested

- The primary Scanner hint remains advisory.
- Its contribution is capped below Manager's auto-classification threshold.
- Non-primary Scanner scores are capped below Manager's conflict threshold.
- Fundamental and Technical evidence must corroborate the final decision.

### Review

- Scanner review is not treated as a source conflict.
- Scanner does not receive a primary hint in Manager's sanitized classifier view.
- Scanner scores remain weak supporting evidence only.
- Manager resolves the candidate from Fundamental and Technical contracts.

### Conflict

A real Scanner `conflict` remains fail-closed and blocks a new BUY through the
analysis-evidence gate.

## Generic tags

Machine-oriented tags are ignored by Manager classification:

```text
bucket-hint:*
bucket-candidate:*
bucket-hint-status:*
strategy-bucket:*
```

Human-readable tags are supporting evidence only. They cannot create another
bucket identity or trigger a conflict. Broad Core tags such as `quality`,
`stable`, and `cash-flow` cannot classify `core_dividend` without explicit
income evidence.

## Core identity rules

Manager no longer treats `Financial Services` as a defensive/income identity.
Quality, positive free cash flow, and low leverage are not enough by themselves
to create a Core bucket. Explicit dividend evidence or a corroborated Core
identity is required.

When Value and Core overlap only because of sector/quality evidence, explicit
low-PE, low-PB, valuation, or Scanner Value evidence may resolve the candidate
to `value_rebound`. Dividend evidence prevents this override.

## Momentum identity rules

Fundamental growth alone does not create `news_momentum` for a Scanner policy-v3
Value or Review candidate when Technical evidence is weak and no news/catalyst
tag exists. Momentum requires Technical or catalyst corroboration.

## Audit fields

The Manager evidence summary records:

- Scanner policy version
- defining and supporting Scanner evidence
- Scanner dominance rule
- ignored machine tags
- Manager Scanner-policy version
- whether generic tags were treated as supporting only

## Safety

This integration does not change the controlled buckets or Manager classifier
contract:

```text
manager-strategy-bucket-v3
```

Risk approval, Execution validation, Database persistence, and fail-closed BUY
gates remain mandatory.

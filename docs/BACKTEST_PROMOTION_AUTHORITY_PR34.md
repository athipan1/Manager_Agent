# Manager_Agent Backtest Promotion Authority

## Execution authority

Manager_Agent no longer treats a raw Backtest run or nested metadata as execution authority. For every symbol and strategy candidate it requests the latest exact promotion from Database_Agent using:

- account ID
- symbol
- strategy ID
- timeframe
- `nested_walk_forward_v2` validation profile
- maximum evidence age

Database_Agent remains the lifecycle source of truth and prevents an older approved promotion from hiding newer failed or revoked evidence.

## State policy

| Promotion state | Manager action |
|---|---|
| `GENERATED` | block |
| `VALIDATED` | block |
| `OOS_PASSED` | block |
| `ROBUSTNESS_PASSED` | block, or approve only when explicit paper approval policy is enabled |
| `APPROVED_FOR_PAPER` | allow downstream Risk evaluation |
| `PAPER_OBSERVING` | allow downstream Risk evaluation, read-only |
| `REJECTED`, `FAILED`, `EXPIRED`, `REVOKED` | block |

Approval does not authorize an order. The existing flow remains:

`Promotion authority -> Risk_Agent -> Execution_Agent -> paper broker`

Only Execution_Agent may hold a trading broker key or submit an order.

## Approval credential boundary

Manager_Agent uses the normal `DATABASE_AGENT_API_KEY` for exact lookup. It adds `X-PROMOTION-APPROVAL-KEY` only to the privileged `ROBUSTNESS_PASSED -> APPROVED_FOR_PAPER` transition.

Required configuration for automatic paper approval:

```text
BACKTEST_PROMOTION_AUTHORITY_REQUIRED=true
BACKTEST_PROMOTION_AUTO_APPROVE_PAPER=true
BACKTEST_PROMOTION_APPROVAL_TOKEN=<shared approval secret>
BACKTEST_PROMOTION_APPROVER=manager-agent
```

Safe defaults:

- promotion authority follows `BACKTEST_EXECUTION_GATE_REQUIRED`
- automatic paper approval is disabled
- missing approval token fails closed
- LIVE mode is not introduced by this change

## Concurrency and retry

Approval uses expected state and expected version. If another Manager run wins the same transition, the losing caller re-reads the latest exact promotion and proceeds only when Database_Agent now reports `APPROVED_FOR_PAPER` or `PAPER_OBSERVING`. It never guesses the new version.

## Compatibility

The previous raw Backtest validator remains available for diagnostics and migration tests when promotion authority is explicitly disabled. Production execution routes through the promotion façade whenever `BACKTEST_EXECUTION_GATE_REQUIRED` or `BACKTEST_PROMOTION_AUTHORITY_REQUIRED` is enabled.

## Incident response

- Missing promotion: block execution and inspect Backtest publisher/Database lifecycle history.
- Pre-robustness state: do not approve; allow Backtest_Agent to complete evidence gates.
- Stale or expired evidence: create a new Backtest run and promotion.
- Failed/revoked evidence: do not fall back to an older approval.
- Approval CAS conflict: re-read exact authority; do not retry with a guessed version.
- Risk rejection: preserve promotion state; no Execution call.
- Broker reconciliation failure: preserve promotion state and follow existing execution halt policy.

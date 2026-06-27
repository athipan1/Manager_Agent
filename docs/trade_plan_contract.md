# Manager Trade Plan Contract

`TradePlan` is the Manager-owned contract that sits between analysis synthesis and execution.
It prevents the system from turning a plain `buy` / `sell` verdict into an order without a complete risk, sizing, entry, and exit plan.

## Why this exists

Before this contract, downstream services could receive execution intent without one canonical object that answered:

- What symbol are we trading?
- Why are we trading it?
- What is the entry reference price?
- Where is the stop loss?
- How much can this trade lose?
- What risk approval backs this order?
- Is manual approval still required?
- What protective exit should Execution persist?

`TradePlan` makes that explicit and auditable.

## Lifecycle

Recommended status flow:

```text
Draft analysis verdict
  -> TradePlan(status="draft")
  -> Risk_Agent / Database risk approval
  -> TradePlan(status="risk_approved", risk_approval_id="...")
  -> optional manual approval gate
  -> Execution_Agent CreateOrderRequest
```

## Required fields

Core identity:

```json
{
  "plan_id": "uuid-or-idempotency-key",
  "correlation_id": "request-correlation-id",
  "account_id": "1",
  "symbol": "AAPL",
  "side": "buy",
  "quantity": 10,
  "final_verdict": "buy",
  "confidence_score": 0.67
}
```

Risk envelope:

```json
{
  "risk": {
    "account_equity": 10000,
    "cash_available": 5000,
    "max_loss_amount": 50,
    "max_loss_pct": 0.005,
    "risk_per_share": 5,
    "position_value": 1000,
    "position_pct": 0.10,
    "reward_risk_ratio": 2.0,
    "session_risk_loaded": true,
    "portfolio_context_loaded": true
  }
}
```

Exit envelope:

```json
{
  "exit": {
    "stop_loss": 95,
    "take_profit": 110,
    "trailing_stop_pct": 0.08,
    "break_even_trigger_r": 1.0,
    "partial_exit_pct": 0.50,
    "time_stop_minutes": 1440
  }
}
```

## Validation rules added

- Symbols are normalized to uppercase.
- Account IDs are normalized to strings for cross-agent consistency.
- Limit orders require `limit_price`.
- Buy stop-loss must be below entry/limit price.
- Sell stop-loss must be above entry/limit price.
- `final_quantity` defaults to `quantity`.
- `to_execution_order()` refuses to create an execution request unless `risk_approval_id` exists.

## Integration plan

This PR intentionally adds the contract and tests only. The next PR should wire it into:

1. `single_analysis_workflow.py` after synthesis.
2. `risk_workflow.py` so risk approval produces/updates the plan.
3. `execution_workflow.py` so Execution receives `TradePlan.to_execution_order()`.
4. `audit_service.py` so every decision stores the trade plan snapshot.

That keeps the production path safe while giving the Manager a clean upgrade path.

# Manual Review Gate Report Integration

This note documents the safe reporting layer for the Execution_Agent manual review gate.

## Purpose

Manager_Agent can render a `manual_review_gate` response in the hourly report when that key is present in `reports/hourly-auto-trading-report.json`.

The renderer is intentionally read-only from Manager_Agent's perspective. It only formats validation results that already exist in the report payload.

## Expected report key

```json
{
  "manual_review_gate": {
    "status": "success",
    "data": {
      "status": "validated",
      "mode": "manual_order_review_gate",
      "safety": "paper_only_validation_no_broker_state_change",
      "approval_valid": true,
      "execution_enabled": false,
      "ticket_id": "order-review-example",
      "requested_symbols": ["BKNG"],
      "summary": {
        "validated_symbol_count": 1,
        "blocked_symbol_count": 0,
        "orders_changed": false
      },
      "symbols": []
    }
  }
}
```

## Rendered section

The renderer appends a `Broker Manual Review Gate` section showing:

- gate status
- safety mode
- ticket id
- approval validity
- execution enabled flag
- requested symbols
- validated and blocked counts
- per-symbol validation rows
- failed checks when present

## Safety expectation

The gate report must remain a validation/reporting layer only. The report renderer must not perform broker state changes.

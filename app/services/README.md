# Service Layer

This folder is the target home for reusable Manager_Agent helpers.

## Goal

Keep low-level helpers out of `app/main.py` and make them easier to test independently.

## Target modules

```text
services/
  serialization_service.py
  exposure_service.py
  context_service.py
  analysis_service.py
  scanner_candidate_service.py
  audit_service.py
  order_builder.py
```

## Suggested mapping from current `app/main.py`

### `serialization_service.py`

Move pure normalization helpers:

- `_response_to_dict`
- `_normalize_score`
- `_agent_data`
- `_as_decimal`
- `_jsonable`
- `_dict_or_empty`

### `exposure_service.py`

Move exposure helpers:

- `_position_exposure`
- `_total_position_exposure`

### `context_service.py`

Move database/session context helpers:

- `_fetch_context_value`
- `_fetch_session_risk_context`
- `_fetch_session_risk_contexts`

LIVE mode must continue to fail closed when required context cannot be loaded.

### `analysis_service.py`

Move analysis response helpers:

- `_process_agent_response`
- `_analyze_single_asset`
- `_extract_current_price_and_stop`
- `_fundamental_v2_scores`
- `_score_deep_analysis`

### `scanner_candidate_service.py`

Move scanner candidate helpers:

- `_candidate_to_dict`
- `_scanner_candidate_symbol`
- `_scanner_candidate_score`
- `_scanner_candidate_metadata`

### `audit_service.py`

Move audit/report persistence helpers:

- `_dry_run_report`
- `_audit_trade_decision`
- `_persist_signal`

### `order_builder.py`

Move order conversion helpers:

- `_side_from_action`
- `_guard_plan_for_execution`
- `_order_request_from_decision`

## Refactor rule

Prefer moving pure helpers before moving async helpers. Pure helpers are easier to test and less likely to affect trading behavior.

# Manager Agent Organization Plan

This document defines the target internal structure for `Manager_Agent` without creating new repos. `Risk_Agent` and `Execution_Agent` already exist as separate services; this plan focuses on making `Manager_Agent` a cleaner orchestrator.

## Current issue

`app/main.py` currently mixes multiple responsibilities:

- API routes
- account/context loading
- technical + fundamental analysis orchestration
- risk payload preparation
- risk approval persistence
- order request construction
- execution submission
- audit/report generation
- learning-cycle triggering
- scanner/discovery orchestration

That makes the manager harder to test and increases the chance of accidentally bypassing risk or execution guardrails when adding new endpoints.

## Target structure

```text
app/
  main.py
  workflows/
    analyze_workflow.py
    multi_asset_workflow.py
    discovery_workflow.py
    risk_workflow.py
    execution_workflow.py
    learning_workflow.py
  services/
    context_service.py
    analysis_service.py
    audit_service.py
    serialization_service.py
    exposure_service.py
    scanner_candidate_service.py
    order_builder.py
```

## Responsibility split

| Module | Responsibility |
|---|---|
| `main.py` | FastAPI route declarations only. No trading logic. |
| `workflows/analyze_workflow.py` | Single-symbol `/analyze` and `/dry-run/analyze` flow. |
| `workflows/multi_asset_workflow.py` | `/analyze-multi` flow. |
| `workflows/discovery_workflow.py` | Scanner → deep analysis → portfolio allocation flow. |
| `workflows/risk_workflow.py` | Build risk payloads, call risk evaluation helpers, normalize approval decisions. |
| `workflows/execution_workflow.py` | Execute only already-approved risk decisions. |
| `workflows/learning_workflow.py` | Trigger learning and apply/pending policy deltas. |
| `services/context_service.py` | Load balance, positions, open-order exposure, and session risk snapshots. |
| `services/analysis_service.py` | Call technical/fundamental agents and synthesize report details. |
| `services/audit_service.py` | Build dry-run/audit reports and persist signal metadata. |
| `services/serialization_service.py` | `_response_to_dict`, `_jsonable`, `_normalize_score`, and small normalization helpers. |
| `services/exposure_service.py` | Position exposure and total exposure calculations. |
| `services/scanner_candidate_service.py` | Candidate normalization, scoring, metadata extraction. |
| `services/order_builder.py` | Convert approved risk decisions into `CreateOrderRequest`. |

## Safe migration order

### Phase 1 — no behavior change

Create packages and documentation only:

- `app/workflows/`
- `app/services/`
- module README files
- this organization plan

### Phase 2 — move pure helpers first

Move functions that do not call external services:

- `_response_to_dict`
- `_normalize_score`
- `_agent_data`
- `_as_decimal`
- `_jsonable`
- `_dict_or_empty`
- `_position_exposure`
- `_total_position_exposure`
- `_candidate_to_dict`
- `_scanner_candidate_score`
- `_scanner_candidate_metadata`
- `_extract_current_price_and_stop`
- `_fundamental_v2_scores`
- `_score_deep_analysis`

### Phase 3 — move service helpers

Move helpers that call external clients:

- `_fetch_context_value`
- `_fetch_session_risk_context`
- `_fetch_session_risk_contexts`
- `_persist_signal`
- `_audit_trade_decision`

### Phase 4 — move execution helpers

Move order/execution helpers:

- `_ensure_risk_approval_id`
- `_side_from_action`
- `_guard_plan_for_execution`
- `_order_request_from_decision`
- `_execute_trade`
- `_execute_portfolio_batch`

### Phase 5 — move workflows

Move route-backed workflows:

- `_run_single_analysis_flow`
- `_process_multi_asset_analysis`
- `discover_analyze_trade_endpoint` internal logic
- `scan_and_analyze_endpoint` internal logic

After this phase, `main.py` should mostly contain FastAPI routes that delegate to workflow functions.

## Safety rules

1. `ExecutionWorkflow` must never execute a trade unless a risk decision is already approved.
2. LIVE mode must continue to fail closed if required database/session context is unavailable.
3. Risk approval must be persisted before live execution.
4. `MANUAL_APPROVAL_REQUIRED` must be checked before any execution call.
5. Dry-run endpoints must never call `Execution_Agent`.
6. Learning deltas must remain pending unless `APPLY_LEARNING_DELTAS=true`.

## Suggested validation after each phase

Run these checks after each refactor phase:

```bash
python -m compileall app
pytest -q
```

Then run the integration stack:

```bash
docker compose -f docker-compose.yml -f docker-compose.risk.yml up --build
```

Minimum endpoint smoke tests:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/preflight/live
```

Use `/dry-run/analyze` before `/analyze`.

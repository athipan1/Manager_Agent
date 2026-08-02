# Nested Backtest Execution Gate

Manager_Agent blocks candidates before Risk and Execution unless Database_Agent contains fresh, exact-symbol Backtest evidence for the selected strategy.

## Preferred evidence profile

```text
nested_walk_forward_v2
```

The legacy profile `rolling_walk_forward_v1` remains readable during migration, but new publishers should write the nested profile.

## Required nested metadata

```json
{
  "validation_profile": "nested_walk_forward_v2",
  "walk_forward_required": true,
  "walk_forward_passed": true,
  "walk_forward_status": "completed",
  "walk_forward_stability_score": 0.91,
  "selection_method": "nested_train_select_test_evaluate",
  "walk_forward_criteria": {
    "train_bars": 126,
    "test_bars": 126,
    "step_bars": 126,
    "min_windows": 4
  },
  "walk_forward_validation": {
    "status": "completed",
    "selection_method": "nested_train_select_test_evaluate",
    "passed": true,
    "evaluated_windows": 4,
    "overlapping_test_windows": false,
    "latest_selected_strategy_id": "trend-following-balanced-v1",
    "latest_selection_eligible": true,
    "gates": {}
  },
  "promotion_gates": {},
  "statistical_criteria": {
    "enabled": true
  }
}
```

## Fail-closed requirements

Manager requires all of the following:

- the run, skill, strategy, symbol, and timeframe match the exact lookup
- the run and persisted skill result passed
- evidence is fresh enough for `BACKTEST_GATE_MAX_AGE_HOURS`
- the nested validation status is `completed`
- the nested validation and every aggregate gate passed
- test windows are explicitly non-overlapping
- the latest training selection was eligible
- the latest selected strategy ID matches the persisted run strategy ID
- every publisher-defined promotion gate passed
- statistical validation is present and enabled
- the completed window count meets the persisted minimum

Any missing, malformed, disabled, overlapping, mismatched, stale, or failed evidence blocks the symbol before Risk_Agent and Execution_Agent.

## Migration

During rollout, Manager accepts:

```text
nested_walk_forward_v2
rolling_walk_forward_v1
```

The response advertises `nested_walk_forward_v2` as the preferred profile and includes both values in `supported_validation_profiles`.

After all scheduled publishers and stored records have moved to nested evidence, the legacy profile can be removed in a dedicated compatibility change.

# Workflow Layer

This folder is the target home for Manager_Agent orchestration flows.

## Goal

Keep `app/main.py` focused on FastAPI routing and move multi-step trading flows into testable workflow modules.

## Target modules

```text
workflows/
  analyze_workflow.py
  multi_asset_workflow.py
  discovery_workflow.py
  risk_workflow.py
  execution_workflow.py
  learning_workflow.py
```

## Workflow boundaries

### `analyze_workflow.py`
Owns the single-symbol flow behind:

- `POST /analyze`
- `POST /dry-run/analyze`

It should coordinate:

1. Context loading
2. Analysis
3. Risk evaluation
4. Optional execution
5. Audit
6. Learning trigger

### `multi_asset_workflow.py`
Owns the multi-symbol portfolio flow behind:

- `POST /analyze-multi`

It should coordinate batch analysis, portfolio risk decisions, execution outcomes, and learning from the most impactful approved trade.

### `discovery_workflow.py`
Owns scanner/discovery based flows:

- `POST /discover-analyze-trade`
- scanner candidate ranking and allocation

### `risk_workflow.py`
Owns only risk orchestration inside Manager_Agent:

- build risk inputs
- call `assess_trade` / `assess_portfolio_trades`
- normalize approval IDs
- fail closed in LIVE mode

It must not send orders.

### `execution_workflow.py`
Owns only execution orchestration inside Manager_Agent:

- require an approved risk decision
- respect manual approval and dry-run modes
- persist risk approval before live execution
- submit to `Execution_Agent`

It must not calculate risk.

### `learning_workflow.py`
Owns learning-cycle triggering and policy delta handling.

## Refactor rule

Move one responsibility at a time and keep endpoint responses compatible.

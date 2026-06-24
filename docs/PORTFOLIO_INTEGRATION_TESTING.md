# Portfolio Integration Testing

This repo now has two integration layers for Portfolio Allocation Mode.

## 1. CI integration contract test

Run:

```bash
PYTHONPATH=. python -m pytest tests/test_discover_analyze_trade_portfolio_integration.py -q
```

What it validates:

- `/discover-analyze-trade` returns `mode=portfolio_allocation`
- response includes:
  - `allocation_plan`
  - `bucket_selection`
  - `selected_positions`
  - `risk_approvals`
  - `execution_candidates`
  - `portfolio_summary`
- 50/30/20 weights are preserved:
  - `core_dividend = 0.50`
  - `value_rebound = 0.30`
  - `news_momentum = 0.20`
- selected positions include one candidate per bucket
- approved positions are sent through Execution batch
- top-level `winner` and `trade_decision` are not exposed as the primary response contract

This test uses fake downstream clients so it is deterministic and safe for CI.

## 2. Live smoke test with real running agents

Run this only after all agents are running:

- Manager_Agent
- Scanner_Agent
- Fundamental_Agent
- Technical_Agent
- Risk_Agent
- Execution_Agent
- Database_Agent
- Learning_Agent

Safe contract-only mode:

```bash
MANAGER_AGENT_URL=http://localhost:8000 \
python scripts/integration_portfolio_smoke.py --dry-run
```

Paper/simulator execution mode:

```bash
MANAGER_AGENT_URL=http://localhost:8000 \
python scripts/integration_portfolio_smoke.py --execute
```

Use `--execute` only when the environment is configured for PAPER/SIMULATOR trading.

Example with smaller discovery universe:

```bash
MANAGER_AGENT_URL=http://localhost:8000 \
python scripts/integration_portfolio_smoke.py \
  --dry-run \
  --max-universe 20 \
  --top-n 10 \
  --max-workers 2
```

The smoke test fails if Manager falls back to a single-winner response shape.

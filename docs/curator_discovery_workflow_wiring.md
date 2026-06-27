# Curator advisory discovery workflow wiring

This document describes the next controlled step for enabling Curator_Agent inside Manager_Agent discovery.

## Goal

Wire Curator_Agent into `app/workflows/discovery_workflow.py` as advisory metadata only.

Curator output must not:

- approve trades
- reject trades
- change quantity
- change stop loss
- submit broker orders
- bypass Risk_Agent

## Runtime behavior

When enabled through `CURATOR_AGENT_ENABLED=true`, Manager can enrich selected `position_analysis_payloads` with Curator skill output.

The intended output shape in Manager response is:

```json
{
  "curator_signals": [
    {
      "symbol": "ACGL",
      "status": "success",
      "skill_id": "...",
      "skill_name": "RSI Signal",
      "execution": {
        "execution_status": "success",
        "output": {
          "signal": "hold",
          "confidence": 0.55,
          "reason": "Curator advisory only"
        }
      }
    }
  ]
}
```

The hourly report already renders this field after PR #170.

## Patch script

This PR adds:

```bash
scripts/patch_curator_discovery_workflow.py
```

Run it locally from the Manager_Agent repo root:

```bash
python scripts/patch_curator_discovery_workflow.py
```

Then review the diff carefully:

```bash
git diff app/workflows/discovery_workflow.py
```

Expected changes:

1. Import `enrich_payloads_with_curator_signals`.
2. Enrich `position_analysis_payloads` after allocation.
3. Attach `curator_signal` to persisted signal metadata.
4. Return `curator_signals` in response data.
5. Add `portfolio_summary.curator_signals` count.

## Validation

Run focused tests first:

```bash
PYTHONPATH=. python -m pytest -q tests/test_curator_client.py tests/services/test_curator_signal_service.py tests/test_render_hourly_portfolio_report.py
```

Then run full tests:

```bash
PYTHONPATH=. python -m pytest -q
```

## Safe deployment

Start with Curator disabled:

```bash
CURATOR_AGENT_ENABLED=false docker compose -f docker-compose.yml -f docker-compose.curator.yml up -d --build
```

Then test Curator runtime:

```bash
python scripts/check_curator_runtime.py
```

Only after the runtime smoke test passes, enable advisory mode:

```bash
CURATOR_AGENT_ENABLED=true docker compose -f docker-compose.yml -f docker-compose.curator.yml up -d --build
```

## Safety reminder

Even after wiring, Curator is still only an advisor. Risk_Agent and Execution_Agent remain the only approval/execution authorities.

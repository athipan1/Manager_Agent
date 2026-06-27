# Curator Agent integration plan

This document describes the safe Manager_Agent integration path for Curator_Agent.

## Current PR scope

This PR adds the support layer only:

- `app/curator_client.py`
- `app/services/curator_signal_service.py`
- tests for disabled/fallback/success behavior

The support layer is intentionally best-effort and signal-only. It does not alter order sizing, risk approvals, or execution behavior.

## Intended flow

```text
Manager_Agent discovery payload
        ↓
Curator signal enrichment, best effort
        ↓
metadata.curator_signal attached to selected payload
        ↓
existing Risk_Agent checks
        ↓
existing Execution_Agent guarded path
```

## Safety constraints

- Curator is disabled by default with `CURATOR_AGENT_ENABLED=false`.
- Curator failures return diagnostics and must not block Manager.
- Curator output is advisory metadata in this phase.
- Curator must not place orders.
- Risk_Agent remains the authority for approvals.
- Execution_Agent remains the only broker-order path.

## Environment variables

```text
CURATOR_AGENT_ENABLED=false
CURATOR_AGENT_URL=http://curator-agent:8010
CURATOR_AGENT_TIMEOUT=5
CURATOR_AGENT_MAX_RETRIES=1
CURATOR_AGENT_FAILURE_THRESHOLD=2
CURATOR_AGENT_COOLDOWN_SECONDS=30
CURATOR_SKILL_TIMEOUT_SECONDS=1.0
```

## Manual workflow wiring patch

The final workflow hook should be reviewed separately before enabling in production because it touches the trading path.

Recommended location in `app/workflows/discovery_workflow.py` after `position_analysis_payloads` is built:

```python
from ..services.curator_signal_service import enrich_payloads_with_curator_signals

position_analysis_payloads, curator_signals = await enrich_payloads_with_curator_signals(
    payloads=position_analysis_payloads,
    correlation_id=correlation_id,
)
```

Then include `curator_signals` in the returned response for report visibility:

```python
"curator_signals": curator_signals,
"portfolio_summary": {
    ...,
    "curator_signals": len(curator_signals),
}
```

Do not use Curator output to approve, size, or submit orders until a later PR adds explicit risk-reviewed rules.

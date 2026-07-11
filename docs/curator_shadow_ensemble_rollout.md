# Curator Shadow Ensemble Rollout

Manager_Agent now supports Curator_Agent's `/skills/shadow-ensemble` contract in the discovery flow.

## Default deployment mode

`docker-compose.curator.yml` enables the shadow ensemble but keeps it advisory:

```env
CURATOR_SHADOW_ENSEMBLE_ENABLED=true
CURATOR_SHADOW_ENSEMBLE_REQUIRED=false
CURATOR_SHADOW_ENSEMBLE_MIN_AGREEMENT=0.60
CURATOR_SHADOW_ENSEMBLE_MAX_SKILLS=8
CURATOR_SHADOW_ENSEMBLE_TIMEOUT=8.0
```

In advisory mode every candidate continues to Risk_Agent, while Curator consensus, agreement, safety-contract validation, and rejection codes are attached to the payload metadata and persisted with discovery telemetry.

## Required-mode promotion criteria

Do not enable required mode until the observation window confirms all of the following:

- Curator availability is at least 99% across scheduled runs.
- No unsafe or malformed Manager contract is observed.
- At least 50 ensemble observations have been collected.
- BUY consensus at the configured threshold has enough coverage to avoid blocking the entire discovery flow unintentionally.
- HOLD/SELL and low-agreement decisions match operator expectations.
- Risk_Agent remains mandatory and no direct-execution permission appears.

## Enable fail-closed gating

After the criteria above are met:

```env
CURATOR_SHADOW_ENSEMBLE_ENABLED=true
CURATOR_SHADOW_ENSEMBLE_REQUIRED=true
```

Required mode removes a candidate before Risk_Agent when Curator is unavailable, the contract is invalid, consensus is not BUY, or agreement is below the configured threshold.

## Rollback

Set either of the following and restart the stack:

```env
CURATOR_SHADOW_ENSEMBLE_REQUIRED=false
```

or disable the new endpoint entirely:

```env
CURATOR_SHADOW_ENSEMBLE_ENABLED=false
```

The legacy single-skill advisory path remains available when the ensemble is disabled.

# Curator Agent runtime setup

This guide explains how to run Curator_Agent beside Manager_Agent without changing the default trading flow.

## What this adds

`docker-compose.curator.yml` adds:

- `curator-agent` service on port `8010`
- persistent `curator_data` volume for the skill registry
- Manager environment variables for the Curator client
- Curator disabled by default via `CURATOR_AGENT_ENABLED=false`

## Start with Curator disabled

This is the safest first run. Curator is available in Docker, but Manager will not call it yet.

```bash
docker compose -f docker-compose.yml -f docker-compose.curator.yml up -d --build
```

## Check health

```bash
curl http://localhost:8010/health
```

Expected result includes:

```json
{
  "status": "success",
  "agent_type": "curator-agent"
}
```

## Enable Curator signal enrichment

Only enable after Curator_Agent PR #2 is deployed and at least one skill has been validated and approved.

```bash
CURATOR_AGENT_ENABLED=true \
docker compose -f docker-compose.yml -f docker-compose.curator.yml up -d --build
```

## Safety behavior

Manager_Agent uses Curator as advisory signal metadata only:

- Curator does not place orders.
- Curator does not receive broker keys.
- Curator is disabled by default.
- Curator failures should not break Manager.
- Risk_Agent remains responsible for approval.
- Execution_Agent remains the only order submission path.

## Seed a test skill

After Curator is running, register and approve a simple test skill:

```bash
curl -X POST http://localhost:8010/skills/register \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Manager Metadata Echo Signal",
    "description": "Returns a harmless hold signal from Manager payload metadata.",
    "tags": ["technical", "manager", "test"],
    "code": "def manager_echo_signal(symbol, analysis, ticker):\n    return {\"signal\": \"hold\", \"confidence\": 0.5, \"reason\": \"Curator test skill active\"}"
  }'
```

Copy the returned `skill_id`, then approve it:

```bash
curl -X POST http://localhost:8010/skills/<skill_id>/approve \
  -H 'Content-Type: application/json' \
  -d '{"approved_by":"operator","reason":"Runtime connectivity test"}'
```

## Compose files

Use this pair for normal Curator-enabled local integration:

```bash
docker compose -f docker-compose.yml -f docker-compose.curator.yml ps
```

Use existing trading safety environment variables as before. Curator does not replace Risk_Agent or Execution_Agent.

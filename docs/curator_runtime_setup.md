# Curator Agent runtime setup

This guide explains how to run Curator_Agent beside Manager_Agent while preserving the mandatory Risk_Agent and Execution_Agent boundaries.

## Runtime contract

`docker-compose.curator.yml` adds:

- `curator-agent` on port `8010`
- persistent `curator_data` storage
- authenticated Manager-to-Curator calls
- authenticated Curator-to-Database calls
- advisory-only skill execution and policy review

Curator credentials have no built-in default. Compose fails before startup when either required value is missing:

```bash
export CURATOR_AGENT_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export CURATOR_ADMIN_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

Use a secret manager or protected deployment environment for persistent production credentials. Do not commit these values to the repository.

## Start the stack

Start with Manager calls disabled while validating the service itself:

```bash
export CURATOR_AGENT_ENABLED=false
docker compose -f docker-compose.yml -f docker-compose.curator.yml up -d --build
```

Check the public operational endpoint:

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

Enable advisory signal enrichment after health, authentication, sandbox availability, and an approved skill have been verified:

```bash
export CURATOR_AGENT_ENABLED=true
docker compose -f docker-compose.yml -f docker-compose.curator.yml up -d --build
```

## Credential roles

Manager uses `CURATOR_AGENT_API_KEY` for read and execute operations such as recommendation, skill execution, and shadow ensemble.

Administrative lifecycle operations use `CURATOR_ADMIN_API_KEY`, including register, approve, deprecate, version, promote, rollback, and performance-policy curation.

Operational endpoints remain open:

```text
GET /health
GET /ready
GET /version
```

All other endpoints require `X-API-KEY` because compose sets `CURATOR_REQUIRE_API_KEY=true`.

## Seed a test skill

Register with the admin credential:

```bash
curl -X POST http://localhost:8010/skills/register \
  -H "X-API-KEY: ${CURATOR_ADMIN_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{
    "name": "Manager Metadata Echo Signal",
    "description": "Returns a harmless hold signal from Manager payload metadata.",
    "tags": ["technical", "manager", "test"],
    "code": "def manager_echo_signal(symbol, analysis, ticker):\n    return {\"signal\": \"hold\", \"confidence\": 0.5, \"reason\": \"Curator test skill active\"}"
  }'
```

Approve the returned `skill_id` with the same admin credential:

```bash
curl -X POST http://localhost:8010/skills/<skill_id>/approve \
  -H "X-API-KEY: ${CURATOR_ADMIN_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"approved_by":"operator","reason":"Runtime connectivity test"}'
```

Execute with the execute-role credential:

```bash
curl -X POST http://localhost:8010/skills/<skill_id>/execute \
  -H "X-API-KEY: ${CURATOR_AGENT_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"inputs":{"symbol":"TEST","ticker":"TEST","analysis":{}}}'
```

## Scheduled workflow behavior

`Bucket Profit Review` generates random Curator execute and admin credentials for each isolated GitHub Actions run, masks them in logs, and passes the same values to Manager and Curator. Persistent deployment workflows must provide managed secrets instead.

## Safety behavior

- Curator remains advisory-only and receives no broker credentials.
- Risk_Agent remains mandatory before execution.
- Execution_Agent remains the only order-submission path.
- Manager fails closed in production when Curator is enabled without its execute credential.
- Curator fails startup when compose authentication credentials are absent.
- Sandbox fallback remains disabled unless an operator explicitly accepts the downgrade.

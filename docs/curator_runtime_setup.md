# Curator Agent runtime setup

This guide runs Curator_Agent beside Manager_Agent while preserving the mandatory Risk_Agent and Execution_Agent boundaries.

## Runtime topology

`docker-compose.curator.yml` now adds three separate runtime surfaces:

- `curator-agent` on port `8010`, responsible for registry, approval, schema validation, telemetry and Manager-facing authentication;
- `curator-sandbox-worker` on the private internal Compose network, responsible only for authenticated sandbox execution;
- `curator-skill-sandbox-image`, a build-only service that ensures the immutable execution image is present on the Docker host.

The request path is:

```text
Manager_Agent
    -> Curator API
    -> signed private worker request
    -> ephemeral hardened skill container
```

The Curator API has no Docker CLI and does not receive `/var/run/docker.sock`. Only the worker receives Docker-daemon access. The worker is not published to a host port.

## Required credentials

Curator credentials have no built-in runtime default. Generate three different values:

```bash
export CURATOR_AGENT_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export CURATOR_ADMIN_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export CURATOR_SANDBOX_WORKER_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
```

Use a secret manager or protected deployment environment for persistent credentials. Do not commit or print these values.

The roles are intentionally separate:

- `CURATOR_AGENT_API_KEY`: Manager read and execute operations;
- `CURATOR_ADMIN_API_KEY`: skill registration, approval and lifecycle administration;
- `CURATOR_SANDBOX_WORKER_API_KEY`: HMAC signing between the API and worker only.

## Pin the runtime images

Production must use images tagged with a tested Git commit SHA rather than mutable `latest` tags:

```bash
export CURATOR_IMAGE_TAG=<curator-agent-git-sha>
```

The compose overlay uses the same tag for:

```text
painaidee/curator-agent:<sha>
painaidee/curator-sandbox-worker:<sha>
painaidee/curator-skill-sandbox:<sha>
```

When building locally, Compose builds all three images from the checked-out `Curator_Agent` directory.

## Start with Manager calls disabled

Keep Manager enrichment disabled while validating the topology:

```bash
export CURATOR_AGENT_ENABLED=false
docker compose \
  -f docker-compose.yml \
  -f docker-compose.curator.yml \
  up -d --build
```

The worker mounts the Docker socket. This grants host-equivalent Docker control and must be used only with a dedicated or rootless execution daemon. The API container must never receive this mount.

## Verify liveness and readiness

Liveness confirms the API process is running:

```bash
curl http://localhost:8010/health
```

Readiness confirms the complete signed execution chain is available:

```bash
curl http://localhost:8010/ready
```

The readiness response must report:

```json
{
  "data": {
    "ready": true,
    "execution": {
      "mode": "remote_worker",
      "secure_execution_ready": true,
      "fallback_enabled": false
    }
  }
}
```

A missing worker, unavailable Docker daemon or missing sandbox image must return HTTP `503`. Do not enable Curator when readiness is unavailable.

## Run the authenticated smoke flow

From `Manager_Agent`:

```bash
python scripts/check_curator_runtime.py
```

A successful result must include:

```text
execution_status=success
execution_backend=remote_worker
sandbox.mode=container
fallback_used=false
sandbox.network_access=false
sandbox.read_only_filesystem=true
```

## Enable advisory enrichment

Enable Manager-to-Curator calls only after the signed worker contract and smoke flow pass:

```bash
export CURATOR_AGENT_ENABLED=true
docker compose \
  -f docker-compose.yml \
  -f docker-compose.curator.yml \
  up -d --build
```

Curator remains advisory-only. It does not receive Alpaca credentials and cannot submit orders. Risk_Agent remains mandatory, and Execution_Agent remains the only order-submission path.

## GitHub Actions behavior

`Curator Worker Contract` generates three ephemeral credentials, starts the worker and API on separate execution surfaces, and proves:

- the API has no Docker CLI or socket;
- the worker is reachable only through its private network;
- signed readiness succeeds;
- Manager executes an approved skill through the worker;
- the ephemeral skill container has no network and a read-only filesystem;
- stopping the worker makes readiness return `503` and execution fail closed without fallback.

Scheduled workflows that use `docker-compose.curator.yml` must generate or inject `CURATOR_SANDBOX_WORKER_API_KEY` in addition to the existing execute and admin credentials.

## Hourly Paper rollout gate

`docker-compose.hourly-paper.yml` intentionally keeps:

```yaml
CURATOR_AGENT_ENABLED: "false"
```

Do not change this value until the cross-repository worker contract passes on `main` and a separate advisory-only Hourly Paper soak test completes without duplicate decisions, fallback execution or readiness failures.

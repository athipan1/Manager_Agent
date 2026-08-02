# Curator Agent runtime setup

This guide runs Curator_Agent beside Manager_Agent while preserving the mandatory Risk_Agent and Execution_Agent boundaries.

## Runtime topology

`docker-compose.curator.yml` adds three separate runtime surfaces:

- `curator-agent` on port `8010`, responsible for registry, approval, schema validation, telemetry and Manager-facing authentication;
- `curator-sandbox-worker` on the private internal Compose network, responsible only for authenticated sandbox execution;
- `curator-skill-sandbox-image`, a build-only service that ensures the execution image is present on the Docker host.

The request path is:

```text
Manager_Agent
    -> Curator API
    -> signed private worker request
    -> ephemeral hardened skill container
```

The Curator API has no Docker CLI and does not receive `/var/run/docker.sock`. Only the worker receives Docker-daemon access. The worker is not published to a host port and receives no Alpaca, Execution_Agent, Risk_Agent or Database_Agent credentials.

## Required credentials

Curator credentials have no built-in runtime default. Generate three different values:

```bash
export CURATOR_AGENT_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export CURATOR_ADMIN_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
export CURATOR_SANDBOX_WORKER_API_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')"
```

Use a secret manager or protected deployment environment for persistent credentials. Do not commit, print or paste these values.

The roles are intentionally separate:

- `CURATOR_AGENT_API_KEY`: Manager read and execute operations;
- `CURATOR_ADMIN_API_KEY`: skill registration, approval and lifecycle administration;
- `CURATOR_SANDBOX_WORKER_API_KEY`: HMAC signing between the API and worker only.

## Host-visible execution workspace

The worker runs in a container while calling the host Docker daemon. Docker bind-mount source paths are resolved on the daemon host, not in the worker container. The temporary skill input must therefore live at the identical absolute path on both sides.

The Compose contract fixes that path to:

```text
/var/lib/curator-worker
```

It configures:

```env
CURATOR_SANDBOX_WORK_ROOT=/var/lib/curator-worker
CURATOR_REQUIRE_SANDBOX_WORK_ROOT=true
```

and mounts:

```yaml
- /var/lib/curator-worker:/var/lib/curator-worker
```

Create the directory on a dedicated execution host when the runtime does not create bind-source directories automatically:

```bash
sudo install -d -m 0700 /var/lib/curator-worker
```

Do not change only one side of the mount. A different host and container path causes Docker-outside-of-Docker bind execution to fail. Missing or unusable workspace configuration makes Curator readiness and execution fail closed.

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
  up -d --build curator-agent
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
      "fallback_enabled": false,
      "worker_execution": {
        "mode": "container",
        "shared_work_root_configured": true,
        "shared_work_root_required": true
      }
    }
  }
}
```

A missing worker, unavailable Docker daemon, missing sandbox image or unusable shared workspace must return HTTP `503`. Do not enable Curator when readiness is unavailable.

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
sandbox.shared_work_root_configured=true
sandbox.shared_work_root_required=true
sandbox.network_access=false
sandbox.read_only_filesystem=true
```

The shared directory must be empty after execution because the worker removes every temporary execution directory.

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

`Curator Worker Integration` generates four ephemeral credentials, starts the real Curator and Database dependency chain from Compose, and proves:

- the API has no Docker CLI or socket;
- the worker is reachable only through its private network and has no published port;
- the Docker socket and shared work root exist only on the worker;
- signed readiness succeeds and reports the shared root contract;
- Manager registers, approves and executes a skill through the worker;
- the ephemeral skill container has no network and a read-only filesystem;
- the worker workspace is empty after execution;
- fallback, broker access and order placement remain disabled.

Persistent workflows that use `docker-compose.curator.yml` must inject `CURATOR_SANDBOX_WORKER_API_KEY` in addition to the existing execute and admin credentials.

## Hourly Paper rollout gate

`docker-compose.hourly-paper.yml` intentionally keeps:

```yaml
CURATOR_AGENT_ENABLED: "false"
```

Do not change this value until the cross-repository worker integration passes on `main` and a separate advisory-only Hourly Paper soak test completes without duplicate decisions, fallback execution or readiness failures.

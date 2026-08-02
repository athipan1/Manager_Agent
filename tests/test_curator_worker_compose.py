from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CURATOR_COMPOSE = ROOT / "docker-compose.curator.yml"
HOURLY_PAPER_COMPOSE = ROOT / "docker-compose.hourly-paper.yml"
WORKER_WORKFLOW = ROOT / ".github" / "workflows" / "curator-worker-contract.yml"
BUCKET_WORKFLOW = ROOT / ".github" / "workflows" / "bucket-profit-review.yml"


def _service_block(compose: str, service: str, next_service: str | None) -> str:
    start = compose.index(f"  {service}:\n")
    end = len(compose) if next_service is None else compose.index(
        f"  {next_service}:\n",
        start + 1,
    )
    return compose[start:end]


def test_worker_is_the_only_service_with_docker_socket() -> None:
    compose = CURATOR_COMPOSE.read_text(encoding="utf-8")
    worker = _service_block(compose, "curator-sandbox-worker", "curator-agent")
    api = _service_block(compose, "curator-agent", None)

    assert compose.count("/var/run/docker.sock:/var/run/docker.sock") == 1
    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in worker
    assert "/var/run/docker.sock" not in api
    assert "dockerfile: worker.Dockerfile" in worker
    assert "read_only: true" in worker
    assert "cap_drop:\n      - ALL" in worker
    assert "no-new-privileges:true" in worker
    assert "ports:" not in worker
    assert 'expose:\n      - "8020"' in worker


def test_api_requires_signed_remote_worker_and_disables_local_fallback() -> None:
    compose = CURATOR_COMPOSE.read_text(encoding="utf-8")
    api = _service_block(compose, "curator-agent", None)

    assert "CURATOR_SANDBOX_WORKER_URL: http://curator-sandbox-worker:8020" in api
    assert (
        "CURATOR_SANDBOX_WORKER_API_KEY: "
        "${CURATOR_SANDBOX_WORKER_API_KEY:?CURATOR_SANDBOX_WORKER_API_KEY is required}"
    ) in api
    assert 'CURATOR_REQUIRE_SANDBOX_WORKER: "true"' in api
    assert 'CURATOR_ALLOW_INSECURE_WORKER_HTTP: "true"' in api
    assert 'CURATOR_CONTAINER_SANDBOX_ENABLED: "false"' in api
    assert 'CURATOR_CONTAINER_SANDBOX_FALLBACK: "false"' in api
    assert "condition: service_healthy" in api
    assert "urlopen('http://localhost:8010/ready'" in api
    assert "read_only: true" in api


def test_worker_network_is_internal_and_sandbox_image_is_prebuilt() -> None:
    compose = CURATOR_COMPOSE.read_text(encoding="utf-8")

    assert "curator-skill-sandbox-image:" in compose
    assert "dockerfile: sandbox/Dockerfile" in compose
    assert "condition: service_completed_successfully" in compose
    assert "curator_worker:\n    internal: true" in compose


def test_hourly_paper_keeps_curator_disabled() -> None:
    hourly = HOURLY_PAPER_COMPOSE.read_text(encoding="utf-8")

    assert 'CURATOR_AGENT_ENABLED: "false"' in hourly


def test_cross_repo_worker_contract_uses_ephemeral_distinct_credentials() -> None:
    workflow = WORKER_WORKFLOW.read_text(encoding="utf-8")

    assert "Generate ephemeral Curator credentials" in workflow
    assert "CURATOR_SANDBOX_WORKER_API_KEY" in workflow
    assert "secrets.token_urlsafe(48)" in workflow
    assert "Verify API has no Docker CLI or socket" in workflow
    assert "Verify fail-closed behavior when worker stops" in workflow
    assert "rejected_remote_worker_unavailable" in workflow


def test_bucket_review_generates_a_distinct_ephemeral_worker_key() -> None:
    workflow = BUCKET_WORKFLOW.read_text(encoding="utf-8")

    assert "CURATOR_IMAGE_TAG: bucket-${{ github.run_id }}" in workflow
    assert 'worker_key="$(python -c \'import secrets; print(secrets.token_urlsafe(48))\')"' in workflow
    assert 'echo "::add-mask::${worker_key}"' in workflow
    assert (
        'echo "CURATOR_SANDBOX_WORKER_API_KEY=${worker_key}" >> "$GITHUB_ENV"'
        in workflow
    )
    assert "Generated Curator credentials must be distinct." in workflow
    assert "curator-sandbox-worker curator-agent manager-agent" in workflow
    assert 'TRADING_MODE: PAPER' in workflow
    assert 'ALLOW_LIVE_TRADING: "false"' in workflow
    assert 'DRY_RUN: "true"' in workflow

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CURATOR_COMPOSE = ROOT / "docker-compose.curator.yml"
HOURLY_PAPER = ROOT / "docker-compose.hourly-paper.yml"
BUCKET_REVIEW = ROOT / ".github" / "workflows" / "bucket-profit-review.yml"


def _service_block(compose: str, service: str, next_service: str) -> str:
    start = compose.index(f"  {service}:\n")
    end = compose.index(f"  {next_service}:\n", start)
    return compose[start:end]


def test_worker_secret_and_shared_root_are_required() -> None:
    compose = CURATOR_COMPOSE.read_text(encoding="utf-8")

    assert (
        "${CURATOR_SANDBOX_WORKER_API_KEY:?CURATOR_SANDBOX_WORKER_API_KEY is required}"
        in compose
    )
    assert "CURATOR_SANDBOX_WORK_ROOT: /var/lib/curator-worker" in compose
    assert 'CURATOR_REQUIRE_SANDBOX_WORK_ROOT: "true"' in compose
    assert "- /var/lib/curator-worker:/var/lib/curator-worker" in compose


def test_docker_socket_is_exposed_only_to_worker() -> None:
    compose = CURATOR_COMPOSE.read_text(encoding="utf-8")
    worker = _service_block(compose, "curator-sandbox-worker", "curator-agent")
    curator_api = compose[compose.index("  curator-agent:\n") :]

    assert "/var/run/docker.sock:/var/run/docker.sock:ro" in worker
    assert "/var/run/docker.sock" not in curator_api
    assert "dockerfile: worker.Dockerfile" in worker
    assert "read_only: true" in worker
    assert "cap_drop:" in worker and "- ALL" in worker
    assert "no-new-privileges:true" in worker


def test_worker_has_no_trading_credentials_or_published_port() -> None:
    compose = CURATOR_COMPOSE.read_text(encoding="utf-8")
    worker = _service_block(compose, "curator-sandbox-worker", "curator-agent")

    assert "expose:" in worker
    assert "ports:" not in worker
    forbidden = (
        "ALPACA_API_KEY",
        "ALPACA_SECRET_KEY",
        "EXECUTION_API_KEY",
        "DATABASE_AGENT_API_KEY",
        "RISK_ADMIN_TOKEN",
    )
    for name in forbidden:
        assert name not in worker


def test_api_requires_remote_worker_and_truthful_readiness() -> None:
    compose = CURATOR_COMPOSE.read_text(encoding="utf-8")
    curator_api = compose[compose.index("  curator-agent:\n") :]

    assert "CURATOR_SANDBOX_WORKER_URL: http://curator-sandbox-worker:8020" in curator_api
    assert 'CURATOR_REQUIRE_SANDBOX_WORKER: "true"' in curator_api
    assert 'CURATOR_CONTAINER_SANDBOX_ENABLED: "false"' in curator_api
    assert 'CURATOR_CONTAINER_SANDBOX_FALLBACK: "false"' in curator_api
    assert "http://localhost:8010/ready" in curator_api
    assert "curator-sandbox-worker:" in curator_api
    assert "condition: service_healthy" in curator_api


def test_worker_network_is_internal_and_api_bridges_only_control_plane() -> None:
    compose = CURATOR_COMPOSE.read_text(encoding="utf-8")
    worker = _service_block(compose, "curator-sandbox-worker", "curator-agent")
    curator_api = compose[compose.index("  curator-agent:\n") :]

    assert "networks:\n      - curator_worker" in worker
    assert "networks:\n      - default\n      - curator_worker" in curator_api
    assert "curator_worker:\n    internal: true" in compose


def test_bucket_review_generates_distinct_ephemeral_worker_key() -> None:
    workflow = BUCKET_REVIEW.read_text(encoding="utf-8")

    assert "CURATOR_IMAGE_TAG: bucket-${{ github.run_id }}" in workflow
    assert "Generate ephemeral Curator credentials" in workflow
    assert "worker_key=" in workflow
    assert "CURATOR_SANDBOX_WORKER_API_KEY=${worker_key}" in workflow
    assert "Generated Curator credentials must be distinct." in workflow
    assert "curator-sandbox-worker curator-agent manager-agent" in workflow
    assert "TRADING_MODE: PAPER" in workflow
    assert 'ALLOW_LIVE_TRADING: "false"' in workflow
    assert 'DRY_RUN: "true"' in workflow


def test_hourly_paper_remains_curator_disabled() -> None:
    hourly = HOURLY_PAPER.read_text(encoding="utf-8")

    assert 'CURATOR_AGENT_ENABLED: "false"' in hourly

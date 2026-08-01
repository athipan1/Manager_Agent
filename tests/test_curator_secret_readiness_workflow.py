from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
READINESS_WORKFLOW = ROOT / ".github" / "workflows" / "curator-secret-readiness.yml"
HOURLY_COMPOSE = ROOT / "docker-compose.hourly-paper.yml"


def test_readiness_workflow_uses_managed_role_secrets() -> None:
    workflow = READINESS_WORKFLOW.read_text(encoding="utf-8")

    assert "secrets.CURATOR_AGENT_API_KEY" in workflow
    assert "secrets.CURATOR_ADMIN_API_KEY" in workflow
    assert "CURATOR_EXECUTE_API_KEY: ${{ secrets.CURATOR_AGENT_API_KEY }}" not in workflow
    assert "CURATOR_CONTAINER_SANDBOX_ENABLED: \"true\"" in workflow
    assert "CURATOR_CONTAINER_SANDBOX_FALLBACK: \"false\"" in workflow
    assert "sandbox/Dockerfile" in workflow
    assert "secure_execution_ready" in workflow
    assert "network_access" in workflow
    assert "read_only_filesystem" in workflow


def test_readiness_workflow_keeps_credentials_out_of_source() -> None:
    workflow = READINESS_WORKFLOW.read_text(encoding="utf-8")

    forbidden_literals = (
        "contract-execute-key",
        "contract-admin-key",
        "smoke-execute-key",
        "smoke-admin-key",
        "dev_curator_key",
    )
    for literal in forbidden_literals:
        assert literal not in workflow


def test_hourly_paper_curator_stays_disabled_until_readiness_passes() -> None:
    hourly_compose = HOURLY_COMPOSE.read_text(encoding="utf-8")

    assert 'CURATOR_AGENT_ENABLED: "false"' in hourly_compose

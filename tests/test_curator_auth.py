from pathlib import Path

import pytest

from app import curator_auth
from app.curator_client import CuratorAgentClient
from app.curator_ensemble_client import CuratorShadowEnsembleClient


def test_curator_auth_headers_select_role_credentials(monkeypatch):
    monkeypatch.setattr(curator_auth, "CURATOR_AGENT_API_KEY", "execute-key")
    monkeypatch.setattr(curator_auth, "CURATOR_ADMIN_API_KEY", "admin-key")

    assert curator_auth.curator_auth_headers() == {"X-API-KEY": "execute-key"}
    assert curator_auth.curator_auth_headers(admin=True) == {"X-API-KEY": "admin-key"}


def test_curator_auth_headers_are_omitted_when_unconfigured(monkeypatch):
    monkeypatch.setattr(curator_auth, "CURATOR_AGENT_API_KEY", "")
    monkeypatch.setattr(curator_auth, "CURATOR_ADMIN_API_KEY", "")

    assert curator_auth.curator_auth_headers() == {}
    assert curator_auth.curator_auth_headers(admin=True) == {}


def test_curator_compose_requires_external_credentials():
    compose = Path("docker-compose.curator.yml").read_text(encoding="utf-8")

    assert "dev_curator_execute_key" not in compose
    assert "dev_curator_admin_key" not in compose
    assert "${CURATOR_AGENT_API_KEY:?CURATOR_AGENT_API_KEY is required}" in compose
    assert "${CURATOR_ADMIN_API_KEY:?CURATOR_ADMIN_API_KEY is required}" in compose


def test_bucket_review_generates_ephemeral_curator_credentials():
    workflow = Path(".github/workflows/bucket-profit-review.yml").read_text(
        encoding="utf-8"
    )

    assert "Generate ephemeral Curator credentials" in workflow
    assert "secrets.token_urlsafe(32)" in workflow
    assert "CURATOR_AGENT_API_KEY=${execute_key}" in workflow
    assert "CURATOR_ADMIN_API_KEY=${admin_key}" in workflow


@pytest.mark.asyncio
async def test_curator_clients_attach_execute_role_key(monkeypatch):
    monkeypatch.setattr(curator_auth, "CURATOR_AGENT_API_KEY", "execute-key")
    monkeypatch.setattr(curator_auth, "CURATOR_ADMIN_API_KEY", "admin-key")

    client = CuratorAgentClient()
    ensemble_client = CuratorShadowEnsembleClient()
    try:
        assert client._client.headers.get("X-API-KEY") == "execute-key"
        assert ensemble_client._client.headers.get("X-API-KEY") == "execute-key"
    finally:
        await client._client.aclose()
        await ensemble_client._client.aclose()

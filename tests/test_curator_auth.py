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

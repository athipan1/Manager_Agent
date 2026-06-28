import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.system import router


def make_app():
    app = FastAPI()
    app.include_router(router)
    return app


class FakeHealthyDbClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def health(self, correlation_id):
        return {"status": "ok"}


class FakeUnhealthyDbClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def health(self, correlation_id):
        raise RuntimeError("database unavailable")


async def fake_healthy_risk_health(correlation_id=None):
    return {"status": "healthy"}


async def fake_unhealthy_risk_health(correlation_id=None):
    raise RuntimeError("risk unavailable")


def test_health_route_returns_healthy_dependency_status(monkeypatch):
    monkeypatch.setattr("app.routes.system.DatabaseAgentClient", FakeHealthyDbClient)
    monkeypatch.setattr("app.routes.system.check_risk_agent_health_async", fake_healthy_risk_health)
    monkeypatch.setattr("app.routes.system.utc_now", lambda: datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC))

    client = TestClient(make_app())
    response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["dependencies"]["database_agent"]["status"] == "healthy"
    assert body["data"]["dependencies"]["risk_agent"]["status"] == "healthy"


def test_health_route_returns_503_when_database_unhealthy(monkeypatch):
    monkeypatch.setattr("app.routes.system.DatabaseAgentClient", FakeUnhealthyDbClient)
    monkeypatch.setattr("app.routes.system.check_risk_agent_health_async", fake_healthy_risk_health)
    monkeypatch.setattr("app.routes.system.utc_now", lambda: datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC))

    client = TestClient(make_app())
    response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert body["data"]["dependencies"]["database_agent"]["status"] == "unhealthy"
    assert body["data"]["dependencies"]["risk_agent"]["status"] == "healthy"
    assert "database unavailable" in body["data"]["dependencies"]["database_agent"]["details"]


def test_health_route_returns_503_when_risk_agent_unhealthy(monkeypatch):
    monkeypatch.setattr("app.routes.system.DatabaseAgentClient", FakeHealthyDbClient)
    monkeypatch.setattr("app.routes.system.check_risk_agent_health_async", fake_unhealthy_risk_health)
    monkeypatch.setattr("app.routes.system.utc_now", lambda: datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC))

    client = TestClient(make_app())
    response = client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "error"
    assert body["data"]["dependencies"]["database_agent"]["status"] == "healthy"
    assert body["data"]["dependencies"]["risk_agent"]["status"] == "unhealthy"
    assert "risk unavailable" in body["data"]["dependencies"]["risk_agent"]["details"]


def test_preflight_route_delegates_to_stock_preflight(monkeypatch):
    calls = []

    async def fake_run_stock_live_preflight(account_id, sample_symbol, correlation_id):
        calls.append({"account_id": account_id, "sample_symbol": sample_symbol})
        return {
            "approved": True,
            "checks": {"database": {"status": "pass"}},
        }

    monkeypatch.setattr("app.routes.system.config_manager.get", lambda key: "default-account")
    monkeypatch.setattr("app.routes.system.run_stock_live_preflight", fake_run_stock_live_preflight)
    monkeypatch.setattr("app.routes.system.utc_now", lambda: datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC))

    client = TestClient(make_app())
    response = client.get("/preflight/live?sample_symbol=MSFT")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["metadata"]["risk_context_loaded"] is True
    assert calls == [{"account_id": "default-account", "sample_symbol": "MSFT"}]

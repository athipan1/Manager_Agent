import pytest
from fastapi.testclient import TestClient

from app.app_factory import create_app
from app.dashboard_security import DashboardRateLimiter


def minimal_app():
    return create_app(
        include_single_analysis=False,
        include_multi_analysis=False,
        include_discovery=False,
        include_scanner=False,
        include_system=False,
        include_trade_replay=False,
        include_alpha_agents=False,
    )


def test_dashboard_cors_allows_configured_origin(monkeypatch):
    monkeypatch.setenv("DASHBOARD_CORS_ALLOWED_ORIGINS", "https://trading.example.com,http://localhost:5173")
    client = TestClient(minimal_app())
    response = client.options(
        "/dashboard/snapshot",
        headers={
            "Origin": "https://trading.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://trading.example.com"
    assert response.headers.get("access-control-allow-credentials") != "true"


def test_dashboard_cors_rejects_unlisted_origin(monkeypatch):
    monkeypatch.setenv("DASHBOARD_CORS_ALLOWED_ORIGINS", "https://trading.example.com")
    response = TestClient(minimal_app()).options(
        "/dashboard/snapshot",
        headers={
            "Origin": "https://attacker.example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers


def test_dashboard_cors_forbids_production_wildcard(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DASHBOARD_CORS_ALLOWED_ORIGINS", "*")
    with pytest.raises(RuntimeError, match="must not contain"):
        minimal_app()


@pytest.mark.asyncio
async def test_dashboard_rate_limiter_blocks_excess_requests():
    limiter = DashboardRateLimiter(limit=2, window_seconds=60)
    await limiter.check("client", now=100.0)
    await limiter.check("client", now=101.0)
    with pytest.raises(Exception) as exc_info:
        await limiter.check("client", now=102.0)
    assert getattr(exc_info.value, "status_code", None) == 429
    assert exc_info.value.headers["Retry-After"] == "58"

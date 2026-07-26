import json
from pathlib import Path

from scripts.hourly_portfolio_cycle import CycleClients
from scripts.hourly_runtime_loader import _safe_readiness_detail


ALPHA_COMPOSE = Path("docker-compose.alpha.yml")
PAPER_COMPOSE = Path("docker-compose.hourly-paper.yml")


def test_hourly_performance_client_uses_dedicated_api_key(monkeypatch):
    monkeypatch.setenv("PERFORMANCE_AGENT_API_KEY", "performance-key")
    monkeypatch.setenv("PROFIT_AGENT_API_KEY", "profit-key")

    clients = CycleClients("performance-auth-test")

    assert clients.performance.headers == {"X-API-KEY": "performance-key"}


def test_hourly_performance_client_falls_back_to_profit_key(monkeypatch):
    monkeypatch.delenv("PERFORMANCE_AGENT_API_KEY", raising=False)
    monkeypatch.setenv("PROFIT_AGENT_API_KEY", "profit-key")

    clients = CycleClients("performance-auth-fallback-test")

    assert clients.performance.headers == {"X-API-KEY": "profit-key"}


def test_safe_readiness_detail_exposes_checks_but_not_unknown_fields():
    raw = json.dumps(
        {
            "status": "error",
            "data": {
                "ready": False,
                "checks": {
                    "api_authentication": False,
                    "database_agent_configuration": True,
                },
                "secret_value": "must-not-leak",
            },
            "metadata": {
                "failed_checks": ["performance_api_key"],
                "database_url_source": "DATABASE_AGENT_URL",
            },
            "error": {
                "code": "service_not_ready",
                "message": "Required service configuration is incomplete",
                "details": {"secret": "must-not-leak"},
            },
        }
    )

    detail = _safe_readiness_detail(raw)

    assert detail == {
        "status": "error",
        "ready": False,
        "failed_checks": ["performance_api_key"],
        "checks": {
            "api_authentication": False,
            "database_agent_configuration": True,
        },
        "error": {
            "code": "service_not_ready",
            "message": "Required service configuration is incomplete",
        },
    }
    assert "must-not-leak" not in json.dumps(detail)


def test_hourly_paper_compose_wires_same_key_to_manager_and_service():
    alpha = ALPHA_COMPOSE.read_text(encoding="utf-8")
    paper = PAPER_COMPOSE.read_text(encoding="utf-8")

    assert alpha.count(
        "PERFORMANCE_AGENT_API_KEY: ${PROFIT_AGENT_API_KEY:-dev_performance_key}"
    ) == 2
    assert paper.count(
        "PERFORMANCE_AGENT_API_KEY: ${PROFIT_AGENT_API_KEY:?PROFIT_AGENT_API_KEY is required}"
    ) == 2
    assert 'PERFORMANCE_AGENT_AUTH_ENABLED: "false"' not in paper

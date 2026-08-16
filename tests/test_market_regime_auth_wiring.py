from pathlib import Path

from scripts.hourly_runtime_loader import runtime


ALPHA_COMPOSE = Path("docker-compose.alpha.yml")
PAPER_COMPOSE = Path("docker-compose.hourly-paper.yml")


def test_hourly_runtime_requires_market_regime_secret_for_paper():
    assert "MARKET_REGIME_API_KEY" in runtime.SCHEDULED_REQUIRED_SECRETS


def test_alpha_compose_wires_same_market_key_to_manager_and_service():
    alpha = ALPHA_COMPOSE.read_text(encoding="utf-8")

    assert (
        "MARKET_REGIME_AGENT_API_KEY: ${MARKET_REGIME_API_KEY:-dev_market_regime_key}"
        in alpha
    )
    assert (
        "MARKET_REGIME_API_KEY: ${MARKET_REGIME_API_KEY:-dev_market_regime_key}"
        in alpha
    )


def test_hourly_paper_compose_enables_market_auth_fail_closed():
    paper = PAPER_COMPOSE.read_text(encoding="utf-8")

    assert (
        "MARKET_REGIME_AGENT_API_KEY: ${MARKET_REGIME_API_KEY:?MARKET_REGIME_API_KEY is required}"
        in paper
    )
    assert (
        "MARKET_REGIME_API_KEY: ${MARKET_REGIME_API_KEY:?MARKET_REGIME_API_KEY is required}"
        in paper
    )
    assert 'MARKET_REGIME_AUTH_REQUIRED: "true"' in paper
    assert "APP_ENV: production" in paper

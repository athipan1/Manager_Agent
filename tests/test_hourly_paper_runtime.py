from datetime import datetime, timezone

import pytest

from app.hourly_paper_runtime import (
    PAPER_API_URL,
    RuntimeSafetyError,
    check_alpaca_paper,
    check_railway_database,
    deterministic_order_idempotency_key,
    deterministic_portfolio_cycle_id,
    validate_runtime_environment,
)


def scheduled_env():
    return {
        "GITHUB_EVENT_NAME": "schedule",
        "TRADING_ENABLED": "true",
        "TRADING_MODE": "PAPER",
        "BROKER_MODE": "ALPACA",
        "DRY_RUN": "false",
        "ALLOW_LIVE_TRADING": "false",
        "BACKTEST_EXECUTION_GATE_REQUIRED": "true",
        "BROKER_RECONCILE_REQUIRED": "true",
        "BROKER_RECONCILE_CONTEXT_REQUIRED": "true",
        "PERFORMANCE_SESSION_RISK_REQUIRED": "true",
        "ALPACA_API_KEY_ID": "paper-key-value",
        "ALPACA_SECRET_KEY": "paper-secret-value",
        "ALPACA_API_URL": PAPER_API_URL,
        "EXECUTION_API_KEY": "execution-runtime-value",
        "DATABASE_AGENT_URL": "https://database-agent.example.railway.app",
        "DATABASE_AGENT_API_KEY": "database-runtime-value",
        "RISK_ADMIN_TOKEN": "risk-runtime-value",
        "PORTFOLIO_AGENT_API_KEY": "portfolio-runtime-value",
    }


def test_scheduled_runtime_accepts_only_exact_paper_contract():
    report = validate_runtime_environment(scheduled_env())
    assert report["paper_automation"] is True
    assert report["broker_mode"] == "ALPACA"
    assert report["dry_run"] is False


@pytest.mark.parametrize(
    "field",
    [
        "ALPACA_API_KEY_ID",
        "ALPACA_SECRET_KEY",
        "ALPACA_API_URL",
        "EXECUTION_API_KEY",
        "DATABASE_AGENT_URL",
        "DATABASE_AGENT_API_KEY",
        "RISK_ADMIN_TOKEN",
        "PORTFOLIO_AGENT_API_KEY",
    ],
)
def test_missing_scheduled_secret_fails_closed(field):
    env = scheduled_env()
    env[field] = ""
    with pytest.raises(RuntimeSafetyError):
        validate_runtime_environment(env)


@pytest.mark.parametrize(
    "placeholder",
    ["dev_execution_key", "dev_database_key", "dev_portfolio_key", "changeme", "password", "test", "secret"],
)
def test_placeholder_secret_fails_closed(placeholder):
    env = scheduled_env()
    env["EXECUTION_API_KEY"] = placeholder
    with pytest.raises(RuntimeSafetyError):
        validate_runtime_environment(env)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("ALPACA_API_URL", "https://api.alpaca.markets"),
        ("ALLOW_LIVE_TRADING", "true"),
        ("TRADING_MODE", "LIVE"),
        ("BROKER_MODE", "SIMULATOR"),
        ("DRY_RUN", "true"),
    ],
)
def test_scheduled_live_or_simulator_misconfiguration_fails(field, value):
    env = scheduled_env()
    env[field] = value
    with pytest.raises(RuntimeSafetyError):
        validate_runtime_environment(env)


def test_railway_database_requires_connected_persistent_paper_contract(monkeypatch):
    payloads = {
        "/health": {"data": {"database_connection": "connected", "dev_mode": False, "trading_mode": "PAPER", "database_emergency_halt": False}},
        "/ready": {"data": {"ready": True, "dev_mode": False, "database_agent_api_key_configured": True}},
        "/version": {"data": {"agent_type": "database", "version": "1.1.0", "schema_version": "1.0"}},
    }
    monkeypatch.setattr(
        "app.hourly_paper_runtime.JsonHttpClient.request",
        lambda self, path, **kwargs: payloads[path],
    )
    result = check_railway_database(
        base_url="https://database.example.railway.app",
        api_key="key-value",
        correlation_id="cycle-1",
    )
    assert result["health"] == "connected"
    assert result["dev_mode"] is False


def test_railway_sqlite_or_disconnected_database_fails(monkeypatch):
    payloads = {
        "/health": {"data": {"database_connection": "disconnected", "dev_mode": True, "trading_mode": "PAPER"}},
        "/ready": {"data": {"ready": True}},
        "/version": {"data": {"agent_type": "database"}},
    }
    monkeypatch.setattr(
        "app.hourly_paper_runtime.JsonHttpClient.request",
        lambda self, path, **kwargs: payloads[path],
    )
    with pytest.raises(RuntimeSafetyError):
        check_railway_database(
            base_url="https://database.example.railway.app",
            api_key="key-value",
            correlation_id="cycle-1",
        )


def test_market_closed_maps_to_portfolio_review_only(monkeypatch):
    def response(self, path, **kwargs):
        if path == "/v2/account":
            return {"id": "paper-account", "status": "ACTIVE", "trading_blocked": False}
        return {"is_open": False, "timestamp": "2026-07-19T12:00:00Z"}

    monkeypatch.setattr("app.hourly_paper_runtime.JsonHttpClient.request", response)
    result = check_alpaca_paper(
        api_url=PAPER_API_URL,
        api_key_id="key",
        secret_key="secret-value",
        correlation_id="cycle-1",
    )
    assert result["market_open"] is False
    assert result["market_mode"] == "PORTFOLIO_REVIEW_ONLY"


def test_cycle_and_order_idempotency_are_deterministic_and_scoped():
    hour = datetime(2026, 7, 19, 12, 45, tzinfo=timezone.utc)
    cycle = deterministic_portfolio_cycle_id(
        account_id="account-1",
        utc_hour=hour,
    )
    same = deterministic_portfolio_cycle_id(
        account_id="account-1",
        utc_hour=hour,
    )
    assert cycle == same
    assert "account-1" not in cycle
    key = deterministic_order_idempotency_key(
        portfolio_cycle_id=cycle,
        account_id="1",
        symbol="AAPL",
        side="buy",
        strategy_id="hourly-sma-crossover",
        position_lifecycle_id="life-1",
    )
    assert key == deterministic_order_idempotency_key(
        portfolio_cycle_id=cycle,
        account_id="1",
        symbol="AAPL",
        side="buy",
        strategy_id="hourly-sma-crossover",
        position_lifecycle_id="life-1",
    )
    assert key != deterministic_order_idempotency_key(
        portfolio_cycle_id=cycle,
        account_id="1",
        symbol="MSFT",
        side="buy",
        strategy_id="hourly-sma-crossover",
        position_lifecycle_id="life-1",
    )

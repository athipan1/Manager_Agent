from pathlib import Path

import yaml


WORKFLOW_PATH = Path(".github/workflows/hourly-auto-trading.yml")


def workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_hourly_workflow_yaml_parses():
    parsed = yaml.safe_load(workflow_text())
    assert parsed


def test_hourly_schedule_and_concurrency_contract():
    workflow = workflow_text()
    assert '- cron: "5 * * * *"' in workflow
    assert "group: hourly-alpaca-paper-portfolio" in workflow
    assert "cancel-in-progress: false" in workflow
    assert "vars.HOURLY_PAPER_SCHEDULE_ENABLED == 'true'" in workflow


def test_compose_validation_activates_required_backtest_profile():
    workflow = workflow_text()
    assert "docker compose --profile backtest config --quiet" in workflow


def test_hourly_manual_dispatch_defaults_to_simulator_dry_run():
    workflow = workflow_text()
    dry_run = workflow.split("      dry_run:", 1)[1].split(
        "      broker_mode:", 1
    )[0]
    broker = workflow.split("      broker_mode:", 1)[1].split(
        "      max_universe:", 1
    )[0]
    assert "default: true" in dry_run
    assert "default: SIMULATOR" in broker


def test_schedule_forces_exact_alpaca_paper_flags():
    workflow = workflow_text()
    assert "github.event_name == 'schedule' && 'ALPACA'" in workflow
    assert "github.event_name == 'schedule' && 'false'" in workflow
    for required in (
        'TRADING_ENABLED: "true"',
        "TRADING_MODE: PAPER",
        'ALLOW_LIVE_TRADING: "false"',
        'BACKTEST_EXECUTION_GATE_REQUIRED: "true"',
        'BROKER_RECONCILE_REQUIRED: "true"',
        'BROKER_RECONCILE_CONTEXT_REQUIRED: "true"',
        'PERFORMANCE_SESSION_RISK_REQUIRED: "true"',
    ):
        assert required in workflow


def test_workflow_uses_secrets_without_placeholder_fallbacks():
    workflow = workflow_text()
    for name in (
        "ALPACA_API_KEY_ID",
        "ALPACA_SECRET_KEY",
        "ALPACA_API_URL",
        "EXECUTION_API_KEY",
        "DATABASE_AGENT_URL",
        "DATABASE_AGENT_API_KEY",
        "RISK_ADMIN_TOKEN",
        "PORTFOLIO_AGENT_API_KEY",
    ):
        assert f"{name}: ${{{{ secrets.{name} }}}}" in workflow
    assert "secrets.ALPACA_API_URL ||" not in workflow
    assert "dev_execution_key" not in workflow
    assert "dev_database_key" not in workflow
    assert "dev_portfolio_key" not in workflow


def test_paper_runtime_uses_railway_and_not_local_database_service():
    workflow = workflow_text()
    assert "docker-compose.hourly-paper.yml" in workflow
    assert "RUNTIME_DATABASE_AGENT_URL=${DATABASE_AGENT_URL}" in workflow
    start = workflow.split("      - name: Start required agent stack", 1)[1].split(
        "      - name: Wait for required services", 1
    )[0]
    assert "database-agent" not in start
    assert " db" not in start


def test_position_review_precedes_scanner_backtest_and_execution():
    workflow = workflow_text()
    review = workflow.index("Review existing positions, orders, regime, exposure and protection")
    scanner = workflow.index("Run Scanner preselection after portfolio review")
    backtest = workflow.index("Run exact Backtest and publish to Railway Database_Agent")
    execution = workflow.index("Run Manager candidate, Risk and guarded Execution cycle")
    final = workflow.index("Verify fills, protection and post-execution reconciliation")
    assert review < scanner < backtest < execution < final


def test_large_runtime_logic_is_not_embedded_in_yaml():
    workflow = workflow_text()
    assert "python scripts/hourly_paper_preflight.py" in workflow
    assert "python scripts/hourly_portfolio_cycle.py prepare" in workflow
    assert "python scripts/hourly_portfolio_cycle.py trade" in workflow
    assert "python scripts/hourly_portfolio_cycle.py finalize" in workflow
    assert "python - <<'PY'" not in workflow


def test_stale_cleanup_is_identity_scoped_away_from_protection():
    script = Path("scripts/hourly_portfolio_cycle.py").read_text(encoding="utf-8")
    assert "/broker/cleanup/stale-open-orders" in script
    assert "include_protective=false" in script


def test_simulator_and_paper_use_explicit_runtime_overrides():
    workflow = workflow_text()
    assert "docker-compose.hourly-simulator.yml" in workflow
    assert "docker-compose.hourly-paper.yml" in workflow

from pathlib import Path


WORKFLOW = Path(".github/workflows/hourly-auto-trading.yml")


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_hourly_workflow_checks_out_backtest_agent():
    text = workflow_text()
    assert "Checkout Backtest_Agent" in text
    assert "repository: athipan1/Backtest_Agent" in text
    assert "path: Backtest_Agent" in text


def test_backtest_publishes_to_runtime_database_and_fails_closed():
    text = workflow_text()
    assert "DATABASE_AGENT_URL: ${{ env.RUNTIME_DATABASE_AGENT_URL }}" in text
    assert 'PUBLISH_TO_DATABASE: "true"' in text
    assert "python scripts/verify_backtest_publish.py reports/hourly-backtest-result.json" in text


def test_hourly_flow_scans_then_batch_backtests_then_executes_with_exact_gate():
    text = workflow_text()
    review = text.index("Review existing positions, orders, regime, exposure and protection")
    scanner = text.index("Run Scanner preselection after portfolio review")
    batch = text.index(
        "Run exact Backtest and publish to Railway Database_Agent"
    )
    execution = text.index(
        "Run Manager candidate, Risk and guarded Execution cycle"
    )

    assert review < scanner < batch < execution
    assert "python scripts/run_scanner_preselection.py" in text
    assert (
        "BACKTEST_SYMBOLS: "
        "${{ steps.scanner_preselection.outputs.backtest_symbols }}"
    ) in text
    assert "BACKTEST_SYMBOL: ${{ vars.BACKTEST_SYMBOL" not in text


def test_hourly_scanner_preselection_can_reach_manager_from_runner():
    text = workflow_text()
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert '- "8000:80"' in compose
    assert '- "8000:8000"' not in compose
    assert "MANAGER_AGENT_URL: http://localhost:8000" in text
    assert "python scripts/hourly_portfolio_cycle.py wait" in text

def test_database_container_and_backtest_use_the_same_api_key():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "DATABASE_AGENT_API_KEY: ${DATABASE_AGENT_API_KEY:-dev_database_key}" in compose


def test_backtest_report_is_uploaded_with_hourly_reports():
    text = workflow_text()
    assert "verify_backtest_publish.py reports/hourly-backtest-result.json" in text
    assert "path: Manager_Agent/reports/" in text


def test_hourly_workflow_requires_exact_backtest_execution_gate():
    text = workflow_text()
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")

    assert 'BACKTEST_EXECUTION_GATE_REQUIRED: "true"' in text
    assert "BACKTEST_SKILL_ID: ${{ vars.BACKTEST_SKILL_ID" in text
    assert "BACKTEST_STRATEGY_ID: ${{ vars.BACKTEST_STRATEGY_ID" in text
    assert "BACKTEST_TIMEFRAME: ${{ vars.BACKTEST_TIMEFRAME" in text
    assert (
        "BACKTEST_EXECUTION_GATE_REQUIRED: "
        "${BACKTEST_EXECUTION_GATE_REQUIRED:-false}"
    ) in compose

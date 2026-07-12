from pathlib import Path


WORKFLOW = Path(".github/workflows/hourly-auto-trading.yml")


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_hourly_workflow_checks_out_backtest_agent():
    text = workflow_text()
    assert "Checkout Backtest_Agent" in text
    assert "repository: athipan1/Backtest_Agent" in text
    assert "path: Backtest_Agent" in text


def test_backtest_publishes_to_database_container_and_fails_closed():
    text = workflow_text()
    assert "DATABASE_AGENT_URL: http://localhost:8004" in text
    assert 'PUBLISH_TO_DATABASE: "true"' in text
    assert "report.get(\"published\") is not True" in text
    assert 'report.get("publish_status") != "success"' in text
    assert 'database_response.get("status") != "success"' in text


def test_database_container_and_backtest_use_the_same_api_key():
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "DATABASE_AGENT_API_KEY: ${DATABASE_AGENT_API_KEY:-dev_database_key}" in compose


def test_backtest_report_is_uploaded_with_hourly_reports():
    text = workflow_text()
    assert 'Path("reports/hourly-backtest-result.json")' in text
    assert "path: Manager_Agent/reports/" in text

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_publish_workflow_contract():
    workflow = (ROOT / ".github/workflows/publish-dashboard-snapshot.yml").read_text(encoding="utf-8")
    assert 'workflows: ["Hourly Auto Trading"]' in workflow
    assert "types: [completed]" in workflow
    assert "actions: read" in workflow
    assert "contents: write" in workflow
    assert "hourly-auto-trading-report" in workflow
    assert "workflow-metadata.json" in workflow
    assert "dashboard-data" in workflow
    assert "[skip ci]" in workflow
    assert "git pull --rebase" in workflow
    assert "for attempt in 1 2 3" in workflow
    assert "force" not in workflow.lower()
    assert "continue-on-error: true" in workflow
    assert "DASHBOARD_SNAPSHOT_PRIVACY_MODE" in workflow


def test_publish_workflow_does_not_change_trading_safety_flags():
    publish = (ROOT / ".github/workflows/publish-dashboard-snapshot.yml").read_text(encoding="utf-8")
    hourly = (ROOT / ".github/workflows/hourly-auto-trading.yml").read_text(encoding="utf-8")
    assert "ALLOW_LIVE_TRADING" not in publish
    assert "PROFIT_DECISION_EXECUTION_ENABLED" not in publish
    assert "PROFIT_AUTO_EXIT_ALL_ENABLED" not in publish
    assert 'ALLOW_LIVE_TRADING: "false"' in hourly
    assert 'PROFIT_DECISION_EXECUTION_ENABLED: "false"' in hourly
    assert 'PROFIT_AUTO_EXIT_ALL_ENABLED: "false"' in hourly
    assert 'TRADING_MODE: PAPER' in hourly


def test_hourly_artifact_upload_remains_non_blocking_and_always_runs():
    hourly = (ROOT / ".github/workflows/hourly-auto-trading.yml").read_text(encoding="utf-8")
    upload_section = hourly.split("- name: Upload hourly portfolio audit", 1)[1].split("- name:", 1)[0]
    assert "if: always()" in upload_section
    assert "hourly-auto-trading-report" in upload_section
    assert "if-no-files-found: warn" in upload_section

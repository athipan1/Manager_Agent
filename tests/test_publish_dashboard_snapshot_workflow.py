from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_publish_workflow_contract():
    workflow = (
        ROOT / ".github/workflows/publish-dashboard-snapshot.yml"
    ).read_text(encoding="utf-8")
    for name in (
        "Hourly Auto Trading",
        "Alpaca Paper Soak",
        "Manual Alpaca Paper Trading",
    ):
        assert name in workflow
    assert "types: [completed]" in workflow
    assert "push:" in workflow
    assert "branches: [main]" in workflow
    assert "actions: read" in workflow
    assert "contents: write" in workflow
    assert "hourly-auto-trading-report" in workflow
    assert "actions/artifacts?name=hourly-auto-trading-report" in workflow
    assert "workflowName" in workflow
    assert "build_dashboard_fallback_report.py" in workflow
    assert "normalize_hourly_operator_report.py" in workflow
    assert "workflow-metadata.json" in workflow
    assert "dashboard-data" in workflow
    assert "[skip ci]" in workflow
    assert "git pull --rebase" in workflow
    assert "for attempt in 1 2 3" in workflow
    assert "force" not in workflow.lower()
    assert "DASHBOARD_SNAPSHOT_PRIVACY_MODE" in workflow


def test_publish_workflow_keeps_triggering_run_authoritative():
    workflow = (
        ROOT / ".github/workflows/publish-dashboard-snapshot.yml"
    ).read_text(encoding="utf-8")
    event_selection = workflow.index('if [ -n "${EVENT_RUN_ID:-}" ]; then')
    latest_artifact_lookup = workflow.index(
        "actions/artifacts?name=hourly-auto-trading-report"
    )
    assert event_selection < latest_artifact_lookup
    assert 'run_id="$EVENT_RUN_ID"' in workflow
    assert "run_is_authoritative=true" in workflow
    assert 'if [ "$artifact_found" != true ] && has_hourly_artifact "$run_id"' in workflow


def test_artifact_download_runs_inside_manager_checkout():
    workflow = (
        ROOT / ".github/workflows/publish-dashboard-snapshot.yml"
    ).read_text(encoding="utf-8")
    download_section = workflow.split(
        "- name: Download verified hourly report artifact", 1
    )[1].split("- name:", 1)[0]
    assert "working-directory: source" in download_section
    assert "mkdir -p reports/hourly-artifact" in download_section
    assert "--dir reports/hourly-artifact" in download_section
    assert "source/reports/hourly-artifact" not in download_section


def test_artifactless_triggering_run_uses_current_metadata_not_old_cycle():
    workflow = (
        ROOT / ".github/workflows/publish-dashboard-snapshot.yml"
    ).read_text(encoding="utf-8")
    assert "current-run-no-previous-snapshot.json" in workflow
    assert (
        'if [ "${{ steps.hourly_run.outputs.run_is_authoritative }}" = "true" ]'
        in workflow
    )
    assert "The exporter still" in workflow
    assert "preserves lastSuccessfulRun" in workflow


def test_publish_workflow_normalizes_paper_mode_and_rejects_unknown():
    workflow = (
        ROOT / ".github/workflows/publish-dashboard-snapshot.yml"
    ).read_text(encoding="utf-8")
    normalize = workflow.index("normalize_hourly_operator_report.py")
    export = workflow.index("export_dashboard_snapshot.py")
    assert normalize < export
    assert "payload['runtime']['mode'] in {'PAPER', 'SIMULATOR'}" in workflow
    assert "ALPACA_PAPER" not in workflow


def test_publish_workflow_does_not_change_trading_safety_flags():
    publish = (
        ROOT / ".github/workflows/publish-dashboard-snapshot.yml"
    ).read_text(encoding="utf-8")
    hourly = (ROOT / ".github/workflows/hourly-auto-trading.yml").read_text(
        encoding="utf-8"
    )
    assert "ALLOW_LIVE_TRADING" not in publish
    assert "PROFIT_DECISION_EXECUTION_ENABLED" not in publish
    assert "PROFIT_AUTO_EXIT_ALL_ENABLED" not in publish
    assert 'ALLOW_LIVE_TRADING: "false"' in hourly
    assert 'PROFIT_DECISION_EXECUTION_ENABLED: "false"' in hourly
    assert 'PROFIT_AUTO_EXIT_ALL_ENABLED: "false"' in hourly
    assert "TRADING_MODE: PAPER" in hourly


def test_hourly_artifact_upload_remains_non_blocking_and_always_runs():
    hourly = (ROOT / ".github/workflows/hourly-auto-trading.yml").read_text(
        encoding="utf-8"
    )
    upload_section = hourly.split(
        "- name: Upload hourly portfolio audit", 1
    )[1].split("- name:", 1)[0]
    assert "if: always()" in upload_section
    assert "hourly-auto-trading-report" in upload_section
    assert "if-no-files-found: warn" in upload_section

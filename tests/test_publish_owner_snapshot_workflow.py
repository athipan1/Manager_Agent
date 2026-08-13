from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/publish-owner-snapshot.yml"


def workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_owner_snapshot_workflow_accepts_broker_sync_source():
    workflow = workflow_text()
    assert "Broker Sync Check" in workflow
    assert "broker-sync-check-reports" in workflow
    assert "broker-sync-check.json" in workflow
    assert "normalize_broker_sync_owner_report.py" in workflow
    assert 'source_kind="broker-sync"' in workflow


def test_owner_snapshot_workflow_keeps_hourly_source_compatibility():
    workflow = workflow_text()
    for name in (
        "Hourly Auto Trading",
        "Alpaca Paper Soak",
        "Manual Alpaca Paper Trading",
    ):
        assert name in workflow
    assert "hourly-auto-trading-report" in workflow
    assert "normalize_hourly_operator_report.py" in workflow
    assert 'source_kind="hourly"' in workflow


def test_owner_snapshot_workflow_requires_successful_source_run():
    workflow = workflow_text()
    resolve = workflow.split("- name: Resolve source run and artifact", 1)[1].split(
        "- name:", 1
    )[0]
    assert 'conclusion=$(jq -r' in resolve
    assert 'if [ "$conclusion" != "success" ]; then' in resolve
    assert 'echo "publish=false" >> "$GITHUB_OUTPUT"' in resolve


def test_owner_snapshot_workflow_prefers_broker_sync_artifact():
    workflow = workflow_text()
    resolve = workflow.split("- name: Resolve source run and artifact", 1)[1].split(
        "- name:", 1
    )[0]
    broker_index = resolve.index('if [ "$broker_artifact_count" -gt 0 ]; then')
    hourly_index = resolve.index('elif [ "$hourly_artifact_count" -gt 0 ]; then')
    assert broker_index < hourly_index


def test_owner_snapshot_broker_source_is_fail_closed_to_paper_alpaca():
    workflow = workflow_text()
    validation = workflow.split("- name: Validate value-bearing owner snapshot", 1)[
        1
    ].split("- name:", 1)[0]
    assert "payload['runtime']['mode'] == 'PAPER'" in validation
    assert "payload['runtime']['brokerMode'] == 'ALPACA'" in validation
    assert "payload['runtime']['flow'] == 'broker_sync_check'" in validation
    assert "payload['cycle']['status'] == 'success'" in validation


def test_owner_snapshot_full_values_are_ephemeral():
    workflow = workflow_text()
    assert "actions/upload-artifact" not in workflow
    assert "git push" not in workflow
    assert "--privacy-mode full" in workflow
    assert "rm -f reports/latest-owner-dashboard-snapshot.json" in workflow

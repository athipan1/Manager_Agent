from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/hourly-auto-trading.yml")


def _workflow_text() -> str:
    return WORKFLOW_PATH.read_text(encoding="utf-8")


def test_hourly_manual_dispatch_defaults_to_dry_run():
    workflow = _workflow_text()

    dry_run_input = workflow.split("      dry_run:", 1)[1].split(
        "      curator_enabled:", 1
    )[0]

    assert 'default: "true"' in dry_run_input


def test_hourly_schedule_forces_simulator_environment():
    workflow = _workflow_text()

    assert (
        "DRY_RUN: ${{ github.event_name == 'schedule' && 'true' || "
        "github.event.inputs.dry_run || 'true' }}"
    ) in workflow
    assert (
        "BROKER_MODE: ${{ github.event_name == 'schedule' && 'SIMULATOR' || "
        "(github.event.inputs.dry_run || 'true') == 'false' && 'ALPACA' || "
        "'SIMULATOR' }}"
    ) in workflow


def test_hourly_schedule_has_fail_closed_runtime_assertion():
    workflow = _workflow_text()

    assert "Enforce scheduled simulator safety" in workflow
    assert 'if [ "${GITHUB_EVENT_NAME}" = "schedule" ]; then' in workflow
    assert '[ "${DRY_RUN}" != "true" ]' in workflow
    assert '[ "${BROKER_MODE}" != "SIMULATOR" ]' in workflow
    assert "Refusing scheduled run outside Simulator safety mode." in workflow


def test_hourly_simulator_disables_curator_when_isolated_sandbox_is_unavailable():
    workflow = _workflow_text()

    assert "python scripts/seed_curator_advisory_skill.py | tee reports/curator-advisory-status.json" in workflow
    assert 'seed_status=${PIPESTATUS[0]}' in workflow
    assert 'if [ "${seed_status}" -eq 78 ]; then' in workflow
    assert 'echo "CURATOR_AGENT_ENABLED=false" >> "${GITHUB_ENV}"' in workflow
    assert "export CURATOR_AGENT_ENABLED=false" in workflow
    assert "$compose up -d --no-deps --force-recreate manager-agent" in workflow
    assert "manager-agent is healthy with Curator advisory disabled." in workflow
    assert "process fallback forbidden" in workflow


def test_hourly_curator_seed_keeps_non_downgrade_failures_fatal():
    workflow = _workflow_text()

    assert 'if [ "${seed_status}" -ne 0 ]; then' in workflow
    assert "refusing unsafe continuation" in workflow
    assert 'exit "${seed_status}"' in workflow

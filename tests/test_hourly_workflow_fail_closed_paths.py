from pathlib import Path


WORKFLOW = Path(".github/workflows/hourly-auto-trading.yml")


def _workflow_text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_finalize_requires_successful_portfolio_review():
    text = _workflow_text()
    marker = "      - name: Verify fills, protection and post-execution reconciliation\n"
    section = text.split(marker, 1)[1].split("      - name: Render operator report", 1)[0]

    assert "steps.portfolio_review.outcome == 'success'" in section
    assert "if: ${{ !cancelled() }}" not in section


def test_fail_closed_diagnostics_do_not_guess_runtime_when_preflight_failed():
    text = _workflow_text()
    marker = "      - name: Show fail-closed diagnostics\n"
    section = text.split(marker, 1)[1].split("      - name: Stop stack", 1)[0]

    assert 'if [ -z "${COMPOSE_FILE:-}" ]; then' in section
    assert "Runtime stack was not configured; skipping compose diagnostics." in section
    assert "steps.preflight.outputs.paper_automation" not in section
    assert "docker-compose.hourly-simulator.yml" not in section


def test_cleanup_is_noop_when_runtime_stack_was_never_configured():
    text = _workflow_text()
    marker = "      - name: Stop stack\n"
    section = text.split(marker, 1)[1]

    assert 'if [ -z "${COMPOSE_FILE:-}" ]; then' in section
    assert "Runtime stack was not configured; nothing to stop." in section

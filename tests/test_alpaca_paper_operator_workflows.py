from pathlib import Path

import yaml


WORKFLOW_DIR = Path(".github/workflows")


def text(name):
    return (WORKFLOW_DIR / name).read_text(encoding="utf-8")


def test_manual_paper_workflow_reuses_hourly_cycle_and_requires_confirmation():
    workflow = text("manual-alpaca-paper-trading.yml")
    assert yaml.safe_load(workflow)
    assert "EXECUTE_ALPACA_PAPER" in workflow
    assert "uses: ./.github/workflows/hourly-auto-trading.yml" in workflow
    assert "dry_run: false" in workflow
    assert "broker_mode: ALPACA" in workflow
    assert "emergency_halt_drill: true" in workflow
    assert "secrets: inherit" in workflow
    assert "verify_paper_cycle_evidence.py" in workflow
    assert "paper_trading_control.py alert" in workflow


def test_manual_paper_issue_command_is_owner_only_and_closes_with_evidence():
    workflow = text("manual-alpaca-paper-trading.yml")
    assert "issues:" in workflow
    assert "types: [opened]" in workflow
    assert "github.event.issue.title == '[command] Run Manual Alpaca Paper'" in workflow
    assert "github.event.issue.user.login == github.repository_owner" in workflow
    assert "github.actor == github.repository_owner" in workflow
    assert 'OPERATOR_CONFIRMATION="${ISSUE_CONFIRMATION}"' in workflow
    assert "gh issue comment" in workflow
    assert "gh issue close" in workflow


def test_soak_workflow_runs_hourly_with_durable_state_and_failure_halt():
    workflow = text("alpaca-paper-soak.yml")
    assert yaml.safe_load(workflow)
    assert '- cron: "17 * * * *"' in workflow
    assert "START_ALPACA_PAPER_SOAK" in workflow
    assert "STOP_ALPACA_PAPER_SOAK" in workflow
    assert "uses: ./.github/workflows/hourly-auto-trading.yml" in workflow
    assert "paper_trading_control.py record" in workflow
    assert "retention-days: 90" in workflow
    assert "HOURLY_PAPER_SCHEDULE_ENABLED" in workflow
    assert "authorized_soak_schedule: true" in workflow


def test_emergency_halt_workflow_has_no_broker_credentials():
    workflow = text("alpaca-paper-emergency-halt.yml")
    assert yaml.safe_load(workflow)
    assert "HALT_ALPACA_PAPER" in workflow
    assert "CLEAR_ALPACA_PAPER_HALT" in workflow
    assert "issues: write" in workflow
    assert "ALPACA_API_KEY_ID" not in workflow
    assert "ALPACA_SECRET_KEY" not in workflow

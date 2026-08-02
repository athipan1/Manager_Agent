from __future__ import annotations

from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEDULER = ROOT / ".github" / "workflows" / "start-curator-72h-soak.yml"
HOURLY_PAPER = ROOT / "docker-compose.hourly-paper.yml"


def test_scheduler_dispatches_existing_advisory_workflow_hourly() -> None:
    workflow = SCHEDULER.read_text(encoding="utf-8")

    assert 'cron: "25 * * * *"' in workflow
    assert "actions: write" in workflow
    assert "gh workflow run curator-advisory-soak.yml" in workflow
    assert "--ref main" in workflow
    assert "-f cycles=12" in workflow
    assert "-f symbol=TEST" in workflow
    assert "cancel-in-progress: false" in workflow


def test_scheduler_window_is_exactly_72_hours() -> None:
    workflow = SCHEDULER.read_text(encoding="utf-8")

    start_text = 'SOAK_WINDOW_START: "2026-08-02T11:25:00Z"'
    end_text = 'SOAK_WINDOW_END: "2026-08-05T11:25:00Z"'
    assert start_text in workflow
    assert end_text in workflow

    start = datetime.fromisoformat("2026-08-02T11:25:00+00:00")
    end = datetime.fromisoformat("2026-08-05T11:25:00+00:00")
    assert (end - start).total_seconds() == 72 * 60 * 60
    assert "start <= now < end" in workflow


def test_scheduler_has_no_trading_or_broker_credentials() -> None:
    workflow = SCHEDULER.read_text(encoding="utf-8")

    forbidden = (
        "ALPACA_API_KEY_ID",
        "ALPACA_SECRET_KEY",
        "ALLOW_LIVE_TRADING",
        "BROKER_MODE",
        "EXECUTION_API_KEY",
        "RISK_ADMIN_TOKEN",
        "TRADING_ENABLED",
    )
    for name in forbidden:
        assert name not in workflow


def test_hourly_paper_curator_remains_disabled() -> None:
    hourly = HOURLY_PAPER.read_text(encoding="utf-8")

    assert 'CURATOR_AGENT_ENABLED: "false"' in hourly

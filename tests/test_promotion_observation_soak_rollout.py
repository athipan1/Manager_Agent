from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOURLY_WORKFLOW = ROOT / ".github" / "workflows" / "hourly-auto-trading.yml"
SOAK_WORKFLOW = ROOT / ".github" / "workflows" / "alpaca-paper-soak.yml"
PAPER_COMPOSE = ROOT / "docker-compose.hourly-paper.yml"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_hourly_schedule_remains_simulator_dry_run_and_observation_off_by_default():
    workflow = _text(HOURLY_WORKFLOW)

    assert "github.event_name == 'schedule' && 'SIMULATOR'" in workflow
    assert "github.event_name == 'schedule' && 'true' || inputs.dry_run" in workflow
    assert "authorized_soak_schedule:" in workflow
    assert "default: false" in workflow
    assert (
        "BACKTEST_PROMOTION_OBSERVATION_REQUIRED: ${{ "
        "inputs.authorized_soak_schedule == true && 'true' || 'false' }}"
        in workflow
    )
    assert (
        "BACKTEST_PROMOTION_AUTO_APPROVE_PAPER: ${{ "
        "inputs.authorized_soak_schedule == true && 'true' || 'false' }}"
        in workflow
    )


def test_authorized_soak_scopes_approval_token_and_fails_closed_when_missing():
    workflow = _text(HOURLY_WORKFLOW)

    assert (
        "BACKTEST_PROMOTION_APPROVAL_TOKEN: ${{ "
        "inputs.authorized_soak_schedule == true && "
        "secrets.BACKTEST_PROMOTION_APPROVAL_TOKEN || '' }}"
        in workflow
    )
    assert "Validate authorized promotion observation soak" in workflow
    assert (
        "BACKTEST_PROMOTION_APPROVAL_TOKEN is required for authorized "
        "observation soak."
        in workflow
    )


def test_paper_compose_passes_only_explicit_promotion_controls():
    compose = _text(PAPER_COMPOSE)

    assert (
        "BACKTEST_PROMOTION_AUTO_APPROVE_PAPER: "
        "${BACKTEST_PROMOTION_AUTO_APPROVE_PAPER:-false}"
        in compose
    )
    assert (
        "BACKTEST_PROMOTION_OBSERVATION_REQUIRED: "
        "${BACKTEST_PROMOTION_OBSERVATION_REQUIRED:-false}"
        in compose
    )
    assert (
        "BACKTEST_PROMOTION_APPROVAL_TOKEN: "
        "${BACKTEST_PROMOTION_APPROVAL_TOKEN:-}"
        in compose
    )
    assert 'ALLOW_LIVE_TRADING: "false"' in compose
    assert 'TRADING_MODE: PAPER' in compose


def test_soak_caller_is_the_only_workflow_authorizing_the_soak_flag():
    soak = _text(SOAK_WORKFLOW)
    hourly = _text(HOURLY_WORKFLOW)

    assert "authorized_soak_schedule: true" in soak
    assert "secrets: inherit" in soak
    assert "authorized_soak_schedule:" in hourly
    assert "PAPER_SCHEDULE_AUTHORIZED:" in hourly

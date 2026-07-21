from pathlib import Path

import pytest

from scripts.configure_simulator_runtime import (
    SimulatorRuntimeError,
    configure_simulator_runtime,
)


def simulator_env(**overrides):
    env = {
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "TRADING_MODE": "PAPER",
        "BROKER_MODE": "SIMULATOR",
        "DRY_RUN": "true",
        "ALLOW_LIVE_TRADING": "false",
    }
    env.update(overrides)
    return env


def parse_github_env(path: Path) -> dict[str, str]:
    return dict(
        line.split("=", 1)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line
    )


def test_simulator_runtime_creates_unique_job_scoped_internal_keys(tmp_path):
    github_env = tmp_path / "github-env"
    counter = iter(("exec", "database", "portfolio", "risk"))

    names = configure_simulator_runtime(
        github_env,
        environ=simulator_env(),
        token_factory=lambda _: next(counter),
    )

    values = parse_github_env(github_env)
    assert set(names) == {
        "EXECUTION_API_KEY",
        "DATABASE_AGENT_API_KEY",
        "PORTFOLIO_AGENT_API_KEY",
        "RISK_ADMIN_TOKEN",
        "SIMULATOR_RUNTIME_KEYS_EPHEMERAL",
    }
    assert values["EXECUTION_API_KEY"] == "sim-execution-exec"
    assert values["DATABASE_AGENT_API_KEY"] == "sim-database-database"
    assert values["PORTFOLIO_AGENT_API_KEY"] == "sim-portfolio-portfolio"
    assert values["RISK_ADMIN_TOKEN"] == "sim-risk-risk"
    assert values["SIMULATOR_RUNTIME_KEYS_EPHEMERAL"] == "true"
    assert len(set(values[name] for name in names if name.endswith(("KEY", "TOKEN")))) == 4
    assert "DATABASE_AGENT_URL" not in values


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("GITHUB_EVENT_NAME", "schedule"),
        ("TRADING_MODE", "LIVE"),
        ("BROKER_MODE", "ALPACA"),
        ("DRY_RUN", "false"),
        ("ALLOW_LIVE_TRADING", "true"),
    ],
)
def test_simulator_runtime_refuses_non_simulator_or_unsafe_context(tmp_path, field, value):
    with pytest.raises(SimulatorRuntimeError):
        configure_simulator_runtime(
            tmp_path / "github-env",
            environ=simulator_env(**{field: value}),
            token_factory=lambda _: "token",
        )


def test_simulator_runtime_never_writes_values_when_boundary_fails(tmp_path):
    github_env = tmp_path / "github-env"
    with pytest.raises(SimulatorRuntimeError):
        configure_simulator_runtime(
            github_env,
            environ=simulator_env(BROKER_MODE="ALPACA"),
            token_factory=lambda _: "token",
        )
    assert not github_env.exists()

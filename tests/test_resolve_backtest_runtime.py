import json
from pathlib import Path

import pytest

from scripts.resolve_backtest_runtime import (
    API_MINIMUM_BARS,
    DEFAULT_MINIMUM_BARS,
    resolve_minimum_bars,
    write_runtime_contract,
)


@pytest.mark.parametrize(
    ("raw", "resolved", "reason", "adjusted"),
    [
        ("3", DEFAULT_MINIMUM_BARS, "below_api_contract_minimum", True),
        ("99", DEFAULT_MINIMUM_BARS, "below_api_contract_minimum", True),
        ("100", API_MINIMUM_BARS, "accepted", False),
        ("252", DEFAULT_MINIMUM_BARS, "accepted", False),
        ("invalid", DEFAULT_MINIMUM_BARS, "invalid_integer", True),
        ("", DEFAULT_MINIMUM_BARS, "missing_value", True),
    ],
)
def test_resolve_minimum_bars_enforces_backtest_api_contract(
    raw, resolved, reason, adjusted
):
    contract = resolve_minimum_bars(
        {"BACKTEST_MINIMUM_BARS_REQUESTED": raw}
    )

    assert contract["resolved"] == resolved
    assert contract["reason"] == reason
    assert contract["adjusted"] is adjusted
    assert contract["api_minimum"] == 100


def test_resolver_supports_legacy_environment_name():
    contract = resolve_minimum_bars({"BACKTEST_MINIMUM_BARS": "300"})

    assert contract["resolved"] == 300
    assert contract["source"] == "BACKTEST_MINIMUM_BARS"


def test_write_runtime_contract_sets_github_env_and_audit_report(tmp_path):
    github_env = tmp_path / "github-env"
    report = tmp_path / "reports" / "backtest-runtime-contract.json"

    contract = write_runtime_contract(
        github_env_path=github_env,
        report_path=report,
        environ={"BACKTEST_MINIMUM_BARS_REQUESTED": "3"},
    )

    assert github_env.read_text(encoding="utf-8") == (
        f"BACKTEST_MINIMUM_BARS={DEFAULT_MINIMUM_BARS}\n"
    )
    persisted = json.loads(report.read_text(encoding="utf-8"))
    assert persisted["resolved"] == DEFAULT_MINIMUM_BARS
    assert persisted["requested"] == 3
    assert persisted["reason"] == "below_api_contract_minimum"
    assert persisted["timestamp"]
    assert contract["schema_version"] == "backtest-runtime-contract.v1"


def test_hourly_workflow_resolves_repository_value_before_preflight():
    workflow = (
        Path(__file__).resolve().parents[1]
        / ".github"
        / "workflows"
        / "hourly-auto-trading.yml"
    ).read_text(encoding="utf-8")

    assert (
        "BACKTEST_MINIMUM_BARS_REQUESTED: "
        "${{ vars.BACKTEST_MINIMUM_BARS || '252' }}"
    ) in workflow
    assert "- name: Resolve Backtest runtime contract" in workflow
    assert "python scripts/resolve_backtest_runtime.py" in workflow
    assert workflow.index("- name: Resolve Backtest runtime contract") < workflow.index(
        "- name: Validate Paper-only runtime and external dependencies"
    )

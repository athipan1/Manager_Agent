import json
from pathlib import Path

import pytest

from scripts.resolve_backtest_runtime import (
    API_MINIMUM_BARS,
    DEFAULT_MINIMUM_BARS,
    HOURLY_BACKTEST_MODE,
    MARKET_CONTEXT_PATH,
    STRATEGY_BUCKET_REPORT_PATH,
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
        environ={
            "BACKTEST_MINIMUM_BARS_REQUESTED": "3",
            "BACKTEST_MODE": "legacy_fixed",
            "BACKTEST_STRATEGY_BUCKET_AWARE_ENABLED": "false",
        },
    )

    assert github_env.read_text(encoding="utf-8") == (
        f"BACKTEST_MINIMUM_BARS={DEFAULT_MINIMUM_BARS}\n"
        f"BACKTEST_MODE={HOURLY_BACKTEST_MODE}\n"
        "BACKTEST_STRATEGY_BUCKET_AWARE_ENABLED=true\n"
        f"BACKTEST_STRATEGY_BUCKET_REPORT_PATH={STRATEGY_BUCKET_REPORT_PATH}\n"
        f"BACKTEST_MARKET_CONTEXT_PATH={MARKET_CONTEXT_PATH}\n"
    )
    persisted = json.loads(report.read_text(encoding="utf-8"))
    assert persisted["resolved"] == DEFAULT_MINIMUM_BARS
    assert persisted["requested"] == 3
    assert persisted["reason"] == "below_api_contract_minimum"
    assert persisted["timestamp"]
    assert contract["schema_version"] == "backtest-runtime-contract.v2"
    assert persisted["backtest_mode"] == "nested_promotion"
    assert persisted["legacy_fixed_allowed"] is False
    assert persisted["strategy_bucket_aware_enabled"] is True
    assert persisted["strategy_bucket_report_path"] == (
        "reports/hourly-pre-backtest-discovery.json"
    )
    assert persisted["market_context_path"] == "reports/hourly-position-review.json"
    assert persisted["automatic_strategy_fallback_allowed"] is False


def test_hourly_runtime_overrides_unsafe_legacy_operator_drift(tmp_path):
    github_env = tmp_path / "github-env"
    report = tmp_path / "runtime.json"

    write_runtime_contract(
        github_env_path=github_env,
        report_path=report,
        environ={
            "BACKTEST_MINIMUM_BARS_REQUESTED": "252",
            "BACKTEST_MODE": "legacy_fixed",
            "BACKTEST_STRATEGY_BUCKET_AWARE_ENABLED": "false",
            "BACKTEST_STRATEGY_BUCKET_REPORT_PATH": "wrong.json",
            "BACKTEST_MARKET_CONTEXT_PATH": "wrong-market.json",
        },
    )

    rendered = github_env.read_text(encoding="utf-8")
    assert "BACKTEST_MODE=nested_promotion\n" in rendered
    assert "BACKTEST_STRATEGY_BUCKET_AWARE_ENABLED=true\n" in rendered
    assert (
        "BACKTEST_STRATEGY_BUCKET_REPORT_PATH="
        "reports/hourly-pre-backtest-discovery.json\n"
    ) in rendered
    assert "BACKTEST_MARKET_CONTEXT_PATH=reports/hourly-position-review.json\n" in rendered
    assert "legacy_fixed" not in rendered
    assert "wrong.json" not in rendered


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

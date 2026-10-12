"""Execution API keys must align across all existing Paper runtime workflows.

This test never reads or exposes secret values. A mismatch yields an HTTP 401
even when Execution_Agent itself is healthy.
"""
from pathlib import Path

WORKFLOW_DIRECTORY = Path(__file__).resolve().parents[1] / ".github" / "workflows"
PAPER_WORKFLOWS = (
    "hourly-auto-trading.yml",
    "broker-sync-check.yml",
    "bucket-profit-review.yml",
    "paper-protection-reconciliation.yml",
)
CANONICAL = "${{ secrets.EXECUTION_AGENT_API_KEY || secrets.EXECUTION_API_KEY }}"


def test_all_paper_runtime_workflows_use_same_execution_key_for_client_and_container():
    for name in PAPER_WORKFLOWS:
        source = (WORKFLOW_DIRECTORY / name).read_text(encoding="utf-8")
        assert f"EXECUTION_API_KEY: {CANONICAL}" in source, name
        assert f"EXECUTION_AGENT_API_KEY: {CANONICAL}" in source, name
        assert 'ALLOW_LIVE_TRADING: "false"' in source, name


def test_mutating_paper_protection_still_rejects_empty_and_placeholder_keys():
    source = (WORKFLOW_DIRECTORY / "paper-protection-reconciliation.yml").read_text(encoding="utf-8")
    assert 'test -n "${EXECUTION_API_KEY}"' in source
    assert 'test "${EXECUTION_API_KEY}" != "dev_execution_key"' in source
    assert "paper-api.alpaca.markets" in source


def test_bucket_review_fails_closed_before_snapshot_on_invalid_execution_key():
    source = (WORKFLOW_DIRECTORY / "bucket-profit-review.yml").read_text(encoding="utf-8")
    assert '"${EXECUTION_AGENT_API_KEY}" = "dev_execution_key"' in source
    assert 'DRY_RUN: "true"' in source
    assert 'ALLOW_LIVE_TRADING: "false"' in source

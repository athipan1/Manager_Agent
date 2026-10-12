"""Keep the Manager/Database Paper holding scopes identical in Compose E2E."""

import json
from pathlib import Path

import pytest

from scripts.export_unmanaged_paper_scope import export_scope, main

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/unmanaged_broker_holdings.v1.json"


def test_exact_reviewed_paper_scope():
    scope = json.loads(export_scope(CONFIG))
    registry = json.loads(CONFIG.read_text(encoding="utf-8"))
    assert set(scope) == {"1"}
    assert sorted(scope["1"]) == sorted(registry["symbols"])
    assert len(scope["1"]) == 12
    assert registry["safety"]["broker_order_mutation_allowed"] is False


def test_hourly_paper_reconcile_preserves_remote_timeout_and_fail_closed():
    compose = (ROOT / "docker-compose.hourly-paper.yml").read_text(encoding="utf-8")
    assert 'BROKER_SYNC_TIMEOUT_SECONDS: "90"' in compose
    assert 'FAIL_RECONCILE_WHEN_DB_SYNC_FAILS: "true"' in compose
    assert 'ALLOW_LIVE_TRADING: "false"' in compose


def test_compose_db_service_receives_external_scope():
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "UNMANAGED_BROKER_POSITION_SYMBOLS_JSON: ${UNMANAGED_BROKER_POSITION_SYMBOLS_JSON:-}" in compose


@pytest.mark.parametrize("workflow", [
    "hourly-auto-trading.yml", "broker-sync-check.yml",
    "bucket-profit-review.yml", "paper-protection-reconciliation.yml",
])
def test_all_broker_runtime_workflows_export_reviewed_scope(workflow):
    source = (ROOT / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
    assert "Export reviewed Paper external ownership scope" in source
    assert "python scripts/export_unmanaged_paper_scope.py --account-id 1" in source


def test_mismatched_ambient_registry_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_ENV", str(tmp_path / "env.txt"))
    monkeypatch.setenv("UNMANAGED_BROKER_POSITION_SYMBOLS_JSON", '{"1":["NVDA"]}')
    with pytest.raises(SystemExit, match="mismatched"):
        main([])
    assert not (tmp_path / "env.txt").exists()


def test_scope_written_as_single_line_for_github_env(monkeypatch, tmp_path):
    envfile = tmp_path / "env.txt"
    monkeypatch.setenv("GITHUB_ENV", str(envfile))
    monkeypatch.delenv("UNMANAGED_BROKER_POSITION_SYMBOLS_JSON", raising=False)
    assert main([]) == 0
    line = envfile.read_text(encoding="utf-8").strip()
    name, raw = line.split("=", 1)
    assert name == "UNMANAGED_BROKER_POSITION_SYMBOLS_JSON"
    assert json.loads(raw) == json.loads(export_scope(CONFIG))

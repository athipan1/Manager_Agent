from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "docker-compose-e2e.yml"
CHECKS = ROOT / "scripts" / "run_agent_contract_checks.py"


def test_agent_contract_declares_trusted_process_mode() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert 'CURATOR_CONTAINER_SANDBOX_ENABLED: "false"' in workflow
    assert 'CURATOR_CONTAINER_SANDBOX_FALLBACK: "false"' in workflow
    assert "python scripts/run_agent_contract_checks.py" in workflow


def test_agent_contract_requires_truthful_degraded_readiness() -> None:
    checks = CHECKS.read_text(encoding="utf-8")

    assert 'execution.get("mode") == "process"' in checks
    assert 'execution.get("secure_execution_ready") is False' in checks
    assert 'execution.get("degraded") is True' in checks
    assert 'execution.get("fallback_enabled") is False' in checks

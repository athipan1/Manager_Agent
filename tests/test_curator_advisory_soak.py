from __future__ import annotations

from pathlib import Path

import pytest

from scripts.run_curator_advisory_soak import (
    normalize_advisory_output,
    validate_execution,
    validate_readiness,
)


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "curator-advisory-soak.yml"
HOURLY_PAPER = ROOT / "docker-compose.hourly-paper.yml"


def _readiness_payload(*, fallback_enabled: bool = False) -> dict:
    return {
        "status": "success",
        "data": {
            "ready": True,
            "execution": {
                "mode": "remote_worker",
                "secure_execution_ready": True,
                "fallback_enabled": fallback_enabled,
                "worker_execution": {
                    "mode": "container",
                    "image": "painaidee/curator-skill-sandbox:test",
                    "docker_server_version": "28.0.4",
                    "secure_execution_ready": True,
                    "shared_work_root_configured": True,
                    "shared_work_root_required": True,
                },
            },
        },
    }


def _execution_payload(*, fallback_used: bool = False) -> dict:
    return {
        "status": "success",
        "data": {
            "execution_status": "success",
            "execution_backend": "remote_worker",
            "fallback_used": fallback_used,
            "elapsed_ms": 12.5,
            "output": {
                "signal": "hold",
                "confidence": 0.5,
                "reason": "deterministic advisory soak",
            },
            "sandbox": {
                "mode": "container",
                "network_access": False,
                "read_only_filesystem": True,
                "broker_access": False,
                "order_placement": False,
                "shared_work_root_configured": True,
                "shared_work_root_required": True,
            },
        },
    }


def test_readiness_requires_secure_remote_worker_without_fallback() -> None:
    checks = validate_readiness(_readiness_payload())

    assert all(checks.values())

    with pytest.raises(RuntimeError, match="fallback_disabled"):
        validate_readiness(_readiness_payload(fallback_enabled=True))


def test_readiness_checks_runtime_availability_not_execution_metadata() -> None:
    payload = _readiness_payload()
    worker = payload["data"]["execution"]["worker_execution"]

    assert "network_access" not in worker
    assert "read_only_filesystem" not in worker
    assert all(validate_readiness(payload).values())


def test_execution_requires_deterministic_advisory_only_output() -> None:
    expected = _execution_payload()["data"]["output"]
    result = validate_execution(_execution_payload(), expected_output=expected)

    assert all(result["checks"].values())
    assert result["normalized_output"] == expected
    assert result["output_hash"]

    with pytest.raises(RuntimeError, match="fallback_not_used"):
        validate_execution(
            _execution_payload(fallback_used=True),
            expected_output=expected,
        )


def test_advisory_normalization_accepts_representation_only_differences() -> None:
    normalized = normalize_advisory_output(
        {
            "signal": " HOLD ",
            "confidence": "0.5",
            "reason": " deterministic advisory soak ",
            "runtime_note": "ignored non-decision metadata",
        }
    )

    assert normalized == {
        "signal": "hold",
        "confidence": 0.5,
        "reason": "deterministic advisory soak",
    }


def test_execution_rejects_semantically_different_signal() -> None:
    payload = _execution_payload()
    payload["data"]["output"]["signal"] = "buy"
    expected = _execution_payload()["data"]["output"]

    with pytest.raises(RuntimeError, match="deterministic_output"):
        validate_execution(payload, expected_output=expected)


def test_execution_rejects_order_identifiers_in_output() -> None:
    payload = _execution_payload()
    payload["data"]["output"]["order_id"] = "forbidden"
    expected = _execution_payload()["data"]["output"]

    with pytest.raises(RuntimeError, match="no_forbidden_output_keys"):
        validate_execution(payload, expected_output=expected)


def test_scheduled_soak_is_opt_in_and_contains_no_broker_credentials() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "vars.CURATOR_ADVISORY_SOAK_ENABLED == 'true'" in workflow
    assert 'cron: "25 * * * *"' in workflow
    assert "Generate ephemeral Curator credentials" in workflow
    assert "CURATOR_SANDBOX_WORKER_API_KEY" in workflow
    assert "Run deterministic advisory soak cycles" in workflow
    assert "run_curator_advisory_soak.py" in workflow
    assert "Verify worker workspace cleanup" in workflow
    assert "cancel-in-progress: false" in workflow

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


def test_soak_starts_only_curator_dependency_chain() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")

    assert "up --build -d curator-agent" in workflow
    assert "manager-agent" not in workflow
    assert "scanner-agent" not in workflow
    assert "execution-agent" not in workflow


def test_hourly_paper_curator_remains_disabled() -> None:
    hourly = HOURLY_PAPER.read_text(encoding="utf-8")

    assert 'CURATOR_AGENT_ENABLED: "false"' in hourly

import json

from scripts import seed_curator_advisory_skill as seed_script


def _install_curator_responses(monkeypatch, execution):
    monkeypatch.setattr(seed_script, "approved_skill_exists", lambda: False)

    def fake_request_json(path, **kwargs):
        if path == "/health":
            return {"status": "success"}
        if path == "/skills/register":
            return {
                "data": {
                    "skill_id": "skill-123",
                    "validation_status": "validated",
                }
            }
        if path == "/skills/skill-123/approve":
            return {"data": {"approval_status": "approved"}}
        if path == "/skills/skill-123/execute":
            return {"status": "success", "data": execution}
        raise AssertionError(f"Unexpected request path: {path}")

    monkeypatch.setattr(seed_script, "request_json", fake_request_json)


def _sandbox_unavailable_execution():
    return {
        "execution_status": "rejected_no_isolated_sandbox",
        "error": "isolated_container_sandbox_required",
        "container_execution_status": "container_unavailable",
        "container_error": "docker_binary_not_available",
        "fallback_used": False,
    }


def test_simulator_returns_explicit_curator_disabled_exit_code(monkeypatch, capsys):
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("BROKER_MODE", "SIMULATOR")
    _install_curator_responses(monkeypatch, _sandbox_unavailable_execution())

    exit_code = seed_script.main()
    report = json.loads(capsys.readouterr().out)

    assert exit_code == seed_script.SIMULATOR_CURATOR_DISABLED_EXIT_CODE
    assert report["status"] == "curator_disabled_for_simulator"
    assert report["curator_agent_enabled"] is False
    assert report["fallback_used"] is False
    assert report["dry_run"] is True
    assert report["broker_mode"] == "SIMULATOR"


def test_alpaca_mode_fails_closed_when_sandbox_is_unavailable(monkeypatch, capsys):
    monkeypatch.setenv("DRY_RUN", "false")
    monkeypatch.setenv("BROKER_MODE", "ALPACA")
    _install_curator_responses(monkeypatch, _sandbox_unavailable_execution())

    exit_code = seed_script.main()
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert report["ok"] is False
    assert report["stage"] == "execute"


def test_process_fallback_is_rejected_even_if_execution_reports_success(monkeypatch, capsys):
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("BROKER_MODE", "SIMULATOR")
    _install_curator_responses(
        monkeypatch,
        {
            "execution_status": "success",
            "fallback_used": True,
        },
    )

    exit_code = seed_script.main()
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert report["reason"] == "unisolated_process_fallback_rejected"

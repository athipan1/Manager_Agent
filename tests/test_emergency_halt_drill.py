import pytest

from scripts import emergency_halt_drill as drill


def test_halt_drill_rejects_probe_and_restores_readiness(monkeypatch):
    state = {"halted": False}

    def fake_request(base_url, path, *, method="GET", payload=None, admin_token=""):
        if path == "/risk/policy":
            return {"status": "success", "data": {"emergency_halt": state["halted"]}}
        if path == "/risk/halt":
            assert admin_token == "admin-token"
            state["halted"] = True
            return {"status": "success", "data": {"active": True}}
        if path == "/ready":
            return {"status": "error", "data": {"ready": not state["halted"]}}
        if path == "/risk/check":
            assert state["halted"] is True
            return {
                "status": "rejected",
                "data": {
                    "approved": False,
                    "final_quantity": 0,
                    "violations": ["emergency_halt_active"],
                },
            }
        if path == "/risk/halt/clear":
            assert payload["confirm"] is True
            state["halted"] = False
            return {"status": "success", "data": {"active": False}}
        raise AssertionError(path)

    monkeypatch.setattr(drill, "request_json", fake_request)

    report = drill.run_drill(
        base_url="http://risk-agent:8007",
        admin_token="admin-token",
    )

    assert report["status"] == "passed"
    assert report["cleanup"]["cleared"] is True
    assert report["checks"]["risk_probe_rejected"] is True
    assert state["halted"] is False


def test_halt_drill_never_clears_a_preexisting_operator_halt(monkeypatch):
    calls = []

    def fake_request(base_url, path, **kwargs):
        calls.append(path)
        return {"status": "success", "data": {"emergency_halt": True}}

    monkeypatch.setattr(drill, "request_json", fake_request)

    with pytest.raises(drill.DrillError, match="already halted") as exc_info:
        drill.run_drill(
            base_url="http://risk-agent:8007",
            admin_token="admin-token",
        )

    assert calls == ["/risk/policy"]
    assert exc_info.value.report["cleanup"]["attempted"] is False

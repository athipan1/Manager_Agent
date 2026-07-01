from scripts.apply_execution_profit_preview import apply_execution_preview, build_preview_payload


def sample_row(risk_status="approved"):
    return {
        "symbol": "ACGL",
        "bucket": "value_rebound",
        "quantity": 82,
        "entry_price": 96.79,
        "current_price": 98.39,
        "stop_loss": 92.94,
        "profit_request": {
            "position": {
                "symbol": "ACGL",
                "quantity": 82,
                "entry_price": 96.79,
                "current_price": 98.39,
                "stop_loss": 92.94,
            }
        },
        "profit_plan": {
            "symbol": "ACGL",
            "primary_action": "hold",
            "actions": [{"action": "hold", "symbol": "ACGL", "quantity": 0, "reason": "test hold"}],
        },
        "risk_status": risk_status,
        "risk_result": {"approved": risk_status == "approved", "status": risk_status},
    }


def test_build_preview_payload_maps_review_row():
    payload = build_preview_payload(sample_row())
    assert payload["position"]["symbol"] == "ACGL"
    assert payload["position"]["strategy_bucket"] == "value_rebound"
    assert payload["action"]["action"] == "hold"
    assert payload["risk_result"]["approved"] is True
    assert payload["dry_run"] is True


def test_apply_execution_preview_updates_report(monkeypatch):
    calls = []

    def fake_request_json(base_url, path, payload, api_key=None, timeout=30):
        calls.append({"base_url": base_url, "path": path, "payload": payload, "api_key": api_key})
        return {"status": "success", "data": {"approved_for_execution": True, "orders_submitted": False}}

    monkeypatch.setattr("scripts.apply_execution_profit_preview.request_json", fake_request_json)
    report = {"bucket": "value_rebound", "reviewed_positions": [sample_row()], "summary": {"reviewed_positions": 1}, "safety": {}}
    updated = apply_execution_preview(report, "http://localhost:8006", "dev_execution_key")

    assert calls[0]["path"] == "/execution/profit-action-preview"
    assert updated["reviewed_positions"][0]["execution_preview_status"] == "ready"
    assert updated["summary"]["execution_preview_submissions"] == 1
    assert updated["summary"]["execution_preview_ready"] == 1
    assert updated["summary"]["execution_preview_blocked"] == 0
    assert updated["summary"]["execution_submissions"] == 0
    assert updated["safety"]["orders_submitted"] is False


def test_apply_execution_preview_skips_when_risk_not_approved(monkeypatch):
    def fail_request_json(*args, **kwargs):
        raise AssertionError("Execution preview should not be called")

    monkeypatch.setattr("scripts.apply_execution_profit_preview.request_json", fail_request_json)
    report = {"bucket": "value_rebound", "reviewed_positions": [sample_row("rejected")], "summary": {"reviewed_positions": 1}, "safety": {}}
    updated = apply_execution_preview(report, "http://localhost:8006", "dev_execution_key")

    assert updated["reviewed_positions"][0]["execution_preview_status"] == "skipped_risk_not_approved"
    assert updated["summary"]["execution_preview_submissions"] == 0
    assert updated["summary"]["execution_submissions"] == 0
    assert updated["safety"]["orders_submitted"] is False

from scripts.apply_profit_risk_gate import apply_risk_gate, build_gate_payload


def sample_row():
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
            "current_r_multiple": 0.41,
            "unrealized_pl_pct": 0.016,
            "primary_action": "hold",
            "actions": [{"action": "hold", "symbol": "ACGL", "quantity": 0, "reason": "test"}],
        },
    }


def test_build_gate_payload_maps_review_row():
    payload = build_gate_payload(sample_row())
    assert payload["position"]["symbol"] == "ACGL"
    assert payload["position"]["strategy_bucket"] == "value_rebound"
    assert payload["position"]["quantity"] == 82
    assert payload["profit_plan"]["primary_action"] == "hold"
    assert payload["trading_mode"] == "PAPER"


def test_apply_risk_gate_updates_report(monkeypatch):
    calls = []

    def fake_request_json(base_url, path, payload):
        calls.append({"base_url": base_url, "path": path, "payload": payload})
        return {"status": "approved", "data": {"approved": True, "status": "approved"}}

    monkeypatch.setattr("scripts.apply_profit_risk_gate.request_json", fake_request_json)
    report = {"bucket": "value_rebound", "reviewed_positions": [sample_row()], "summary": {"reviewed_positions": 1}, "safety": {}}
    updated = apply_risk_gate(report, "http://risk-agent:8007")

    assert calls[0]["path"] == "/risk/profit-plan-gate"
    assert updated["reviewed_positions"][0]["risk_status"] == "approved"
    assert updated["summary"]["risk_submissions"] == 1
    assert updated["summary"]["risk_approved"] == 1
    assert updated["summary"]["risk_rejected"] == 0
    assert updated["safety"]["risk_agent_submitted"] is True

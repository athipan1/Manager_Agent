from scripts.bucket_profit_review import build_profit_request, parse_bucket_hints, review_bucket


def test_quality_growth_bucket_hints_are_supported():
    assert parse_bucket_hints('{"BKNG":"quality_growth"}') == {"BKNG": "quality_growth"}
    assert parse_bucket_hints("BKNG:quality_growth") == {"BKNG": "quality_growth"}


def test_quality_growth_profit_rules_are_used():
    position = {
        "symbol": "BKNG",
        "strategy_bucket": "quality_growth",
        "quantity": 47,
        "avg_entry_price": 184.65,
        "current_price": 210.00,
    }
    order = {"symbol": "BKNG", "side": "sell", "type": "stop", "status": "new", "stop_price": 170.00}

    payload = build_profit_request("quality_growth", position, order)

    assert payload["first_take_profit_r"] == 2.0
    assert payload["second_take_profit_r"] == 3.5
    assert payload["partial_exit_pct"] == 0.25
    assert payload["trailing_stop_pct"] == 0.10
    assert payload["break_even_trigger_r"] == 1.25


def test_quality_growth_review_selects_bkng(monkeypatch):
    data = {"data": {"positions": []}}
    snapshot = {
        "positions": {"data": [{"symbol": "BKNG", "qty": 47, "avg_entry_price": 184.65, "current_price": 210.00}]},
        "orders": {"data": [{"symbol": "BKNG", "side": "sell", "type": "stop", "status": "new", "stop_price": 170.00}]},
    }

    def fake_plan(url, payload):
        return {
            "symbol": payload["position"]["symbol"],
            "primary_action": "hold",
            "actions": [{"action": "hold", "reason": "Quality growth review hold"}],
            "metadata": {"advisory_only": True},
        }

    monkeypatch.setattr("scripts.bucket_profit_review.call_profit_agent", fake_plan)
    report = review_bucket("quality_growth", data, snapshot, "http://profit-agent", database_bucket_hints={"BKNG": "quality_growth"})

    assert report["bucket"] == "quality_growth"
    assert report["config"]["frequency"] == "weekly"
    assert report["summary"]["reviewed_positions"] == 1
    assert report["reviewed_positions"][0]["symbol"] == "BKNG"

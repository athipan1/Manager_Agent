from scripts.bucket_profit_review import build_profit_request, review_bucket


def test_review_bucket_uses_profit_agent_for_matching_bucket(monkeypatch):
    dashboard = {
        "data": {
            "positions": [
                {
                    "symbol": "ADBE",
                    "strategy_bucket": "core_dividend",
                    "qty": 10,
                    "avg_entry_price": 100,
                    "current_price": 120,
                },
                {
                    "symbol": "CINF",
                    "strategy_bucket": "value_rebound",
                    "qty": 8,
                    "avg_entry_price": 90,
                    "current_price": 95,
                },
            ]
        }
    }
    broker_snapshot = {
        "orders": {
            "data": [
                {"symbol": "ADBE", "side": "sell", "type": "stop", "status": "new", "stop_price": 92},
            ]
        },
        "positions": {"data": []},
    }

    def fake_profit_agent(url, payload):
        return {
            "symbol": payload["position"]["symbol"],
            "primary_action": "partial_exit",
            "actions": [{"action": "partial_exit", "reason": "target reached"}],
            "metadata": {"advisory_only": True},
        }

    monkeypatch.setattr("scripts.bucket_profit_review.call_profit_agent", fake_profit_agent)

    report = review_bucket("core_dividend", dashboard, broker_snapshot, "http://profit-agent")

    assert report["bucket"] == "core_dividend"
    assert report["summary"]["reviewed_positions"] == 1
    assert report["summary"]["profit_agent_used"] == 1
    row = report["reviewed_positions"][0]
    assert row["symbol"] == "ADBE"
    assert row["has_protective_stop"] is True
    assert row["profit_plan"]["primary_action"] == "partial_exit"
    assert report["safety"]["orders_submitted"] is False
    assert report["safety"]["risk_agent_submitted"] is False
    assert report["safety"]["execution_agent_submitted"] is False


def test_build_profit_request_uses_bucket_specific_rules():
    position = {
        "symbol": "ABCD",
        "strategy_bucket": "news_momentum",
        "quantity": 20,
        "avg_entry_price": 50,
        "current_price": 55,
    }
    stop_order = {"symbol": "ABCD", "side": "sell", "type": "stop", "status": "new", "stop_price": 48}

    payload = build_profit_request("news_momentum", position, stop_order)

    assert payload["position"]["symbol"] == "ABCD"
    assert payload["position"]["risk_per_share"] == 2
    assert payload["first_take_profit_r"] == 1.0
    assert payload["second_take_profit_r"] == 1.75
    assert payload["partial_exit_pct"] == 0.50
    assert payload["trailing_stop_pct"] == 0.035


def test_review_bucket_falls_back_without_profit_agent():
    dashboard = {
        "data": {
            "positions": [
                {
                    "symbol": "ACGL",
                    "strategy_bucket": "value_rebound",
                    "qty": 5,
                    "avg_entry_price": 100,
                    "current_price": 109,
                }
            ]
        }
    }
    report = review_bucket("value_rebound", dashboard, {"orders": {"data": []}, "positions": {"data": []}}, None)

    assert report["summary"]["reviewed_positions"] == 1
    assert report["summary"]["positions_without_stop"] == 1
    row = report["reviewed_positions"][0]
    assert row["profit_source"] == "fallback"
    assert row["profit_plan"]["primary_action"] == "move_stop"

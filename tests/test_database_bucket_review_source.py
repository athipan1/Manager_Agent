from scripts.bucket_profit_review import (
    fetch_database_bucket_hints,
    fetch_database_positions,
    merge_bucket_sources,
    review_bucket,
)


def test_database_bucket_hints_override_fallback(monkeypatch):
    dashboard = {"data": {"positions": []}}
    broker_snapshot = {
        "positions": {"data": [{"symbol": "ACGL", "qty": 82, "avg_entry_price": 96.79, "current_price": 98.06}]},
        "orders": {"data": []},
    }

    monkeypatch.setattr(
        "scripts.bucket_profit_review.call_profit_agent",
        lambda url, payload, *_args: {"symbol": payload["position"]["symbol"], "primary_action": "hold", "actions": []},
    )

    report = review_bucket(
        "value_rebound",
        dashboard,
        broker_snapshot,
        "http://profit-agent",
        bucket_hints={"ACGL": "core_dividend"},
        database_bucket_hints={"ACGL": "value_rebound"},
    )

    assert report["summary"]["database_bucket_hints_applied"] == 1
    assert report["summary"]["bucket_hints_applied"] == 0
    assert report["summary"]["reviewed_positions"] == 1
    assert report["reviewed_positions"][0]["bucket_source"] == "database_agent"


def test_merge_bucket_sources_prefers_database_values():
    assert merge_bucket_sources({"ACGL": "value_rebound"}, {"ACGL": "core_dividend", "ADBE": "core_dividend"}) == {
        "ACGL": "value_rebound",
        "ADBE": "core_dividend",
    }


def test_fetch_database_bucket_hints(monkeypatch):
    def fake_request_json(base_url, path, **kwargs):
        assert base_url == "http://database-agent:8004"
        assert path == "/accounts/1/position-buckets"
        assert kwargs["api_key"] == "test-key"
        return {"data": [{"symbol": "ACGL", "strategy_bucket": "value_rebound"}, {"symbol": "BKNG", "strategy_bucket": "unassigned"}]}

    monkeypatch.setattr("scripts.bucket_profit_review._request_json", fake_request_json)

    assert fetch_database_bucket_hints("http://database-agent:8004", 1, "test-key") == {"ACGL": "value_rebound"}


def test_fetch_database_positions_reads_canonical_peak_field(monkeypatch):
    def fake_request_json(base_url, path, **kwargs):
        assert base_url == "http://database-agent:8004"
        assert path == "/accounts/1/positions"
        assert kwargs["api_key"] == "test-key"
        return {
            "data": [
                {
                    "symbol": "ACGL",
                    "quantity": 5,
                    "average_cost": 100,
                    "current_market_price": 110,
                    "highest_price_since_entry": 125,
                    "strategy_bucket": "value_rebound",
                }
            ]
        }

    monkeypatch.setattr("scripts.bucket_profit_review._request_json", fake_request_json)

    rows = fetch_database_positions("http://database-agent:8004", 1, "test-key")
    assert rows[0]["highest_price_since_entry"] == 125

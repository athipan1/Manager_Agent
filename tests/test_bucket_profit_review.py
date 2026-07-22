from scripts.bucket_profit_review import (
    HIGHEST_PRICE_FALLBACK_WARNING,
    build_profit_request,
    call_profit_agent,
    parse_bucket_hints,
    review_bucket,
)


def test_profit_call_forwards_api_key_and_correlation_id(monkeypatch):
    captured = {}

    def fake_request(base_url, path, **kwargs):
        captured.update(base_url=base_url, path=path, **kwargs)
        return {
            "status": "success",
            "data": {"symbol": "ACGL", "primary_action": "hold", "actions": []},
        }

    monkeypatch.setattr("scripts.bucket_profit_review._request_json", fake_request)

    result = call_profit_agent(
        "http://profit-agent:8011",
        {"position": {"symbol": "ACGL"}},
        "profit-key",
        "bucket-correlation-id",
    )

    assert result["symbol"] == "ACGL"
    assert captured["api_key"] == "profit-key"
    assert captured["correlation_id"] == "bucket-correlation-id"
    assert captured["path"] == "/profit/plan"


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

    def fake_profit_agent(url, payload, *_args):
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
    assert payload["schema_version"] == "profit-decision.v2"
    assert payload["position"]["risk_per_share"] == 2
    assert payload["first_take_profit_r"] == 1.0
    assert payload["second_take_profit_r"] == 1.75
    assert payload["partial_exit_pct"] == 0.50
    assert payload["trailing_stop_pct"] == 0.035


def test_build_profit_request_forwards_adaptive_context_without_inference():
    observed_at = "2026-07-22T12:00:00Z"
    position = {
        "symbol": "ACGL",
        "strategy_bucket": "value_rebound",
        "quantity": 10,
        "average_cost": 100,
        "current_market_price": 108,
        "highest_price_since_entry": 120,
        "highest_price_since_entry_source": "database_agent",
        "account_id": 1,
        "position_id": 42,
        "position_version": 7,
        "sources": ["database_agent"],
    }

    payload = build_profit_request(
        "value_rebound",
        position,
        None,
        market_regime={
            "profit_policy_context": {
                "context_version": "profit-market-context.v1",
                "regime": "bear",
                "risk_level": "high",
                "observed_at": observed_at,
            }
        },
        technical_analysis={
            "profit_policy_context": {
                "context_version": "profit-technical-context.v1",
                "trend_strength": 0.2,
                "observed_at": observed_at,
                "evidence_status": "complete",
            }
        },
        max_age_seconds=10**9,
    )

    assert payload["market_context"]["regime"] == "BEAR"
    assert payload["market_context"]["risk_level"] == "HIGH"
    assert payload["market_context"]["trend_strength"] == 0.2
    assert "volume_strength" not in payload["market_context"]
    assert payload["data_quality"]["peak_history_complete"] is True
    assert payload["data_quality"]["position_version_current"] is True


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


def test_parse_bucket_hints_accepts_json_and_csv():
    assert parse_bucket_hints('{"acgl":"value_rebound","ADBE":"core_dividend"}') == {
        "ACGL": "value_rebound",
        "ADBE": "core_dividend",
    }
    assert parse_bucket_hints("ACGL:value_rebound,CINF:value_rebound,NOPE:bad") == {
        "ACGL": "value_rebound",
        "CINF": "value_rebound",
    }


def test_review_bucket_uses_bucket_hints_when_position_bucket_missing(monkeypatch):
    dashboard = {"data": {"positions": []}}
    broker_snapshot = {
        "positions": {
            "data": [
                {"symbol": "ACGL", "qty": 82, "avg_entry_price": 96.79, "current_price": 98.06},
                {"symbol": "BKNG", "qty": 47, "avg_entry_price": 184.65, "current_price": 184.92},
            ]
        },
        "orders": {
            "data": [
                {"symbol": "ACGL", "side": "sell", "type": "stop", "status": "new", "stop_price": 92.94},
            ]
        },
    }

    def fake_profit_agent(url, payload, *_args):
        return {
            "symbol": payload["position"]["symbol"],
            "primary_action": "hold",
            "actions": [{"action": "hold", "reason": "No take-profit or exit condition is triggered"}],
            "metadata": {"advisory_only": True},
        }

    monkeypatch.setattr("scripts.bucket_profit_review.call_profit_agent", fake_profit_agent)

    report = review_bucket(
        "value_rebound",
        dashboard,
        broker_snapshot,
        "http://profit-agent",
        bucket_hints={"ACGL": "value_rebound", "CINF": "value_rebound"},
    )

    assert report["summary"]["positions_seen"] == 2
    assert report["summary"]["bucket_hints_applied"] == 1
    assert report["summary"]["reviewed_positions"] == 1
    assert report["bucket_distribution"] == {"unassigned": 1, "value_rebound": 1}
    row = report["reviewed_positions"][0]
    assert row["symbol"] == "ACGL"
    assert row["bucket_source"] == "bucket_hint"
    assert row["has_protective_stop"] is True


def test_review_bucket_uses_database_highest_price_and_ignores_broker_guess(monkeypatch):
    broker_snapshot = {
        "positions": {
            "data": [
                {
                    "symbol": "ACGL",
                    "qty": 5,
                    "avg_entry_price": 100,
                    "current_price": 110,
                    "highest_price": 999,
                }
            ]
        },
        "orders": {"data": []},
    }
    database_positions = [
        {
            "symbol": "ACGL",
            "quantity": 5,
            "average_cost": 100,
            "current_market_price": 110,
            "highest_price_since_entry": 125,
            "strategy_bucket": "value_rebound",
        }
    ]

    monkeypatch.setattr(
        "scripts.bucket_profit_review.call_profit_agent",
        lambda url, payload, *_args: {
            "symbol": payload["position"]["symbol"],
            "primary_action": "hold",
            "actions": [],
            "warnings": [],
        },
    )

    report = review_bucket(
        "value_rebound",
        {"data": {"positions": []}},
        broker_snapshot,
        "http://profit-agent",
        database_positions=database_positions,
    )

    row = report["reviewed_positions"][0]
    assert row["highest_price_since_entry"] == 125
    assert row["highest_price_since_entry_source"] == "database_agent"
    assert row["profit_request"]["position"]["highest_price_since_entry"] == 125
    assert row["profit_request"]["warnings"] == []
    assert report["warnings"] == []
    assert report["summary"]["position_peak_fallbacks"] == 0


def test_review_bucket_warns_when_database_highest_price_is_unavailable(monkeypatch):
    database_positions = [
        {
            "symbol": "ACGL",
            "quantity": 5,
            "average_cost": 100,
            "current_market_price": 110,
            "highest_price_since_entry": None,
            "strategy_bucket": "value_rebound",
        }
    ]

    monkeypatch.setattr(
        "scripts.bucket_profit_review.call_profit_agent",
        lambda url, payload, *_args: {
            "symbol": payload["position"]["symbol"],
            "primary_action": "hold",
            "actions": [],
            "warnings": [],
        },
    )

    report = review_bucket(
        "value_rebound",
        {"data": {"positions": []}},
        {"positions": {"data": []}, "orders": {"data": []}},
        "http://profit-agent",
        database_positions=database_positions,
    )

    row = report["reviewed_positions"][0]
    assert row["highest_price_since_entry"] == 110
    assert row["highest_price_since_entry_source"] == "current_price_fallback"
    assert row["warnings"] == [HIGHEST_PRICE_FALLBACK_WARNING]
    assert row["profit_request"]["warnings"] == [HIGHEST_PRICE_FALLBACK_WARNING]
    assert HIGHEST_PRICE_FALLBACK_WARNING in row["profit_plan"]["warnings"]
    assert report["warnings"] == [HIGHEST_PRICE_FALLBACK_WARNING]
    assert report["summary"]["position_peak_fallbacks"] == 1

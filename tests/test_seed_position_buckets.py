from scripts.seed_position_buckets import load_assignments, normalize_bucket, seed_position_buckets


def test_normalize_bucket_allows_known_values():
    assert normalize_bucket("core_dividend") == "core_dividend"
    assert normalize_bucket("QUALITY_GROWTH") == "quality_growth"
    assert normalize_bucket("VALUE_REBOUND") == "value_rebound"
    assert normalize_bucket("news_momentum") == "news_momentum"


def test_normalize_bucket_defaults_unknown_to_unassigned():
    assert normalize_bucket("bad_bucket") == "unassigned"
    assert normalize_bucket(None) == "unassigned"


def test_load_assignments_uses_default_seed_values():
    assignments = load_assignments()
    assert {item["symbol"]: item["strategy_bucket"] for item in assignments} == {
        "ADBE": "core_dividend",
        "ACGL": "value_rebound",
        "BKNG": "quality_growth",
        "CINF": "value_rebound",
    }


def test_load_assignments_from_json_filters_invalid_values():
    assignments = load_assignments(
        '[{"symbol":"acgl","strategy_bucket":"value_rebound"},{"symbol":"bkng","strategy_bucket":"quality_growth"},{"symbol":"bad","strategy_bucket":"unknown"},{"symbol":"","strategy_bucket":"core_dividend"}]'
    )
    assert assignments == [
        {
            "symbol": "ACGL",
            "strategy_bucket": "value_rebound",
            "source": "manager_bucket_seed",
            "reason": "seeded by Manager_Agent bucket review workflow",
        },
        {
            "symbol": "BKNG",
            "strategy_bucket": "quality_growth",
            "source": "manager_bucket_seed",
            "reason": "seeded by Manager_Agent bucket review workflow",
        },
    ]


def test_seed_position_buckets_posts_bulk_payload(monkeypatch):
    calls = []

    def fake_request_json(base_url, path, *, payload, api_key=None, timeout=60):
        calls.append({"base_url": base_url, "path": path, "payload": payload, "api_key": api_key, "timeout": timeout})
        return {"status": "success", "data": {"updated_count": 1}}

    monkeypatch.setattr("scripts.seed_position_buckets.request_json", fake_request_json)
    result = seed_position_buckets(
        "http://database-agent:8004",
        "1",
        [{"symbol": "BKNG", "strategy_bucket": "quality_growth", "source": "manager_bucket_seed", "reason": "seed"}],
        api_key="test-key",
    )

    assert result["assignment_count"] == 1
    assert calls == [
        {
            "base_url": "http://database-agent:8004",
            "path": "/accounts/1/position-buckets/bulk",
            "payload": {
                "source": "manager_bucket_seed",
                "assignments": [
                    {"symbol": "BKNG", "strategy_bucket": "quality_growth", "source": "manager_bucket_seed", "reason": "seed"}
                ],
            },
            "api_key": "test-key",
            "timeout": 60,
        }
    ]

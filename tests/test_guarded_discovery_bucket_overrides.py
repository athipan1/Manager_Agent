from app.workflows.guarded_discovery_workflow import (
    _bucket_by_symbol_from_database_sync,
    _bucket_by_symbol_from_response,
    _enrich_broker_state_with_buckets,
    _preflight_bucket_by_symbol_from_database_sync,
)


def test_bucket_backfill_uses_current_selection_and_database_history(monkeypatch):
    monkeypatch.delenv("MANAGER_POSITION_BUCKET_OVERRIDES_JSON", raising=False)
    database_sync = {
        "latest_snapshot": {
            "positions": [
                {"symbol": "BKNG", "strategy_bucket": "value_rebound"},
                {"symbol": "CINF", "strategy_bucket": "core_dividend"},
            ]
        }
    }
    hints = _bucket_by_symbol_from_response(
        {
            "selected_positions": [
                {"symbol": "ADBE", "strategy_bucket": "core_dividend"},
                {"symbol": "ACGL", "strategy_bucket": "value_rebound"},
            ],
            "risk_approvals": [],
            "execution_candidates": [],
        },
        database_sync,
    )

    assert hints == {
        "ADBE": "core_dividend",
        "ACGL": "value_rebound",
        "BKNG": "value_rebound",
        "CINF": "core_dividend",
    }

    enriched = _enrich_broker_state_with_buckets(
        {
            "positions": [
                {"symbol": "CINF", "qty": "46"},
                {"symbol": "ADBE", "qty": "52"},
                {"symbol": "BKNG", "qty": "47"},
                {"symbol": "ACGL", "qty": "82"},
            ],
            "open_orders": [
                {"symbol": "CINF", "id": "stop-cinf"},
                {"symbol": "ADBE", "id": "stop-adbe"},
                {"symbol": "BKNG", "id": "stop-bkng"},
                {"symbol": "ACGL", "id": "stop-acgl"},
            ],
            "summary": {"position_count": 4, "open_order_count": 4},
        },
        hints,
    )

    assert enriched["positions"][0]["strategy_bucket"] == "core_dividend"
    assert enriched["open_orders"][0]["strategy_bucket"] == "core_dividend"
    assert enriched["positions"][2]["strategy_bucket"] == "value_rebound"
    assert enriched["open_orders"][2]["strategy_bucket"] == "value_rebound"
    assert enriched["summary"]["bucket_position_matches"] == 4
    assert enriched["summary"]["bucket_order_matches"] == 4
    assert enriched["bucket_backfill"]["source"] == "selected_positions_and_database_snapshot"


def test_selected_bucket_stays_authoritative_over_database_history(monkeypatch):
    monkeypatch.delenv("MANAGER_POSITION_BUCKET_OVERRIDES_JSON", raising=False)
    hints = _bucket_by_symbol_from_response(
        {
            "selected_positions": [
                {"symbol": "CINF", "strategy_bucket": "value_rebound"},
            ]
        },
        {
            "latest_snapshot": {
                "positions": [
                    {"symbol": "CINF", "strategy_bucket": "core_dividend"},
                ]
            }
        },
    )

    assert hints["CINF"] == "value_rebound"


def test_database_snapshot_bucket_is_preserved_when_symbol_is_not_selected(monkeypatch):
    monkeypatch.delenv("MANAGER_POSITION_BUCKET_OVERRIDES_JSON", raising=False)
    database_sync = {
        "latest_snapshot": {
            "positions": [
                {"symbol": "BKNG", "strategy_bucket": "core_dividend"},
                {"symbol": "CINF", "strategy_bucket": "core_dividend"},
            ],
            "open_orders": [
                {"symbol": "ADBE", "strategy_bucket": "core_dividend"},
            ],
        }
    }

    hints = _bucket_by_symbol_from_response(
        {
            "selected_positions": [
                {"symbol": "ACGL", "strategy_bucket": "value_rebound"},
            ],
            "risk_approvals": [],
            "execution_candidates": [],
        },
        database_sync,
    )

    assert hints["ACGL"] == "value_rebound"
    assert hints["BKNG"] == "core_dividend"
    assert hints["ADBE"] == "core_dividend"
    assert hints["CINF"] == "core_dividend"


def test_current_selection_overrides_previous_database_bucket(monkeypatch):
    monkeypatch.delenv("MANAGER_POSITION_BUCKET_OVERRIDES_JSON", raising=False)
    database_sync = {
        "latest_snapshot": {
            "positions": [
                {"symbol": "BKNG", "strategy_bucket": "value_rebound"},
            ]
        }
    }

    hints = _bucket_by_symbol_from_response(
        {
            "selected_positions": [
                {"symbol": "BKNG", "strategy_bucket": "core_dividend"},
            ]
        },
        database_sync,
    )

    assert hints["BKNG"] == "core_dividend"


def test_database_sync_extracts_buckets_from_database_fallback_shape():
    hints = _bucket_by_symbol_from_database_sync(
        {
            "database": {
                "positions": [
                    {"symbol": "ADBE", "strategy_bucket": "core_dividend"},
                ],
                "open_orders": [
                    {"symbol": "ACGL", "strategy_bucket": "value_rebound"},
                ],
            }
        }
    )

    assert hints == {"ADBE": "core_dividend", "ACGL": "value_rebound"}


def test_preflight_does_not_invent_buckets_when_database_has_no_valid_bucket(monkeypatch):
    monkeypatch.delenv("MANAGER_POSITION_BUCKET_OVERRIDES_JSON", raising=False)
    hints = _preflight_bucket_by_symbol_from_database_sync(
        {
            "latest_snapshot": {
                "positions": [
                    {"symbol": "ACGL", "strategy_bucket": "unassigned"},
                    {"symbol": "ADBE", "strategy_bucket": None},
                    {"symbol": "BKNG", "strategy_bucket": ""},
                    {"symbol": "CINF"},
                ],
                "open_orders": [],
            }
        }
    )

    assert hints == {}


def test_preflight_database_bucket_wins_over_operator_migration_seed(monkeypatch):
    monkeypatch.setenv(
        "MANAGER_POSITION_BUCKET_OVERRIDES_JSON",
        '{"BKNG":"value_rebound","LEGACY":"core_dividend"}',
    )
    hints = _preflight_bucket_by_symbol_from_database_sync(
        {
            "latest_snapshot": {
                "positions": [
                    {"symbol": "BKNG", "strategy_bucket": "core_dividend"},
                ]
            }
        }
    )

    assert hints["BKNG"] == "core_dividend"
    assert hints["LEGACY"] == "core_dividend"

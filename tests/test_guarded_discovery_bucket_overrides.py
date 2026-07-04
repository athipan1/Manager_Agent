from app.workflows.guarded_discovery_workflow import (
    _bucket_by_symbol_from_database_sync,
    _bucket_by_symbol_from_response,
    _enrich_broker_state_with_buckets,
)


def test_bucket_backfill_keeps_cinf_from_becoming_unassigned():
    hints = _bucket_by_symbol_from_response(
        {
            "selected_positions": [
                {"symbol": "ADBE", "strategy_bucket": "core_dividend"},
                {"symbol": "ACGL", "strategy_bucket": "value_rebound"},
            ],
            "risk_approvals": [],
            "execution_candidates": [],
        }
    )

    assert hints["ADBE"] == "core_dividend"
    assert hints["ACGL"] == "value_rebound"
    assert hints["CINF"] == "core_dividend"

    enriched = _enrich_broker_state_with_buckets(
        {
            "positions": [
                {"symbol": "CINF", "qty": "46"},
                {"symbol": "ADBE", "qty": "52"},
            ],
            "open_orders": [
                {"symbol": "CINF", "id": "stop-cinf"},
                {"symbol": "ADBE", "id": "stop-adbe"},
            ],
            "summary": {"position_count": 2, "open_order_count": 2},
        },
        hints,
    )

    assert enriched["positions"][0]["strategy_bucket"] == "core_dividend"
    assert enriched["open_orders"][0]["strategy_bucket"] == "core_dividend"
    assert enriched["summary"]["bucket_position_matches"] == 2
    assert enriched["summary"]["bucket_order_matches"] == 2
    assert enriched["bucket_backfill"]["source"] == "selected_positions_database_snapshot_and_held_position_overrides"


def test_selected_bucket_stays_authoritative_over_default_override():
    hints = _bucket_by_symbol_from_response(
        {
            "selected_positions": [
                {"symbol": "CINF", "strategy_bucket": "value_rebound"},
            ]
        }
    )

    assert hints["CINF"] == "value_rebound"


def test_database_snapshot_bucket_is_preserved_when_symbol_is_not_selected():
    database_sync = {
        "latest_snapshot": {
            "positions": [
                {"symbol": "BKNG", "strategy_bucket": "value_rebound"},
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
    assert hints["BKNG"] == "value_rebound"
    assert hints["ADBE"] == "core_dividend"
    assert hints["CINF"] == "core_dividend"


def test_current_selection_overrides_previous_database_bucket():
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

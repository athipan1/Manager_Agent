from app.workflows.guarded_discovery_workflow import (
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
    assert enriched["bucket_backfill"]["source"] == "selected_positions_and_held_position_overrides"


def test_selected_bucket_stays_authoritative_over_default_override():
    hints = _bucket_by_symbol_from_response(
        {
            "selected_positions": [
                {"symbol": "CINF", "strategy_bucket": "value_rebound"},
            ]
        }
    )

    assert hints["CINF"] == "value_rebound"

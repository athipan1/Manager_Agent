from decimal import Decimal
from types import SimpleNamespace

from app.services.exposure_aware_trade_gate import (
    build_exposure_snapshot,
    evaluate_exposure_aware_trade_gate,
    filter_candidates_with_exposure_gate,
)


def candidate(symbol="NEW", bucket="value_rebound"):
    return {"symbol": symbol, "strategy_bucket": bucket}


def position(symbol, market_value, qty=10, bucket="value_rebound"):
    return SimpleNamespace(
        symbol=symbol,
        market_value=Decimal(str(market_value)),
        quantity=qty,
        strategy_bucket=bucket,
    )


def stop(symbol, qty, status="accepted"):
    return {
        "symbol": symbol,
        "side": "sell",
        "type": "stop",
        "qty": qty,
        "stop_price": "90",
        "status": status,
    }


def test_gate_allows_candidate_when_bucket_and_symbol_have_capacity():
    gate = evaluate_exposure_aware_trade_gate(
        candidate(),
        portfolio_value=Decimal("100000"),
        positions=[],
        open_orders=[],
    )
    assert gate["allowed"] is True
    assert gate["maximum_order_value"] == 7000.0
    assert gate["rejection_codes"] == []


def test_gate_blocks_overweight_bucket():
    held = [position("ACGL", "31000")]
    gate = evaluate_exposure_aware_trade_gate(
        candidate(),
        portfolio_value=Decimal("100000"),
        positions=held,
        open_orders=[stop("ACGL", 10)],
    )
    assert gate["allowed"] is False
    assert "bucket_capacity_exhausted" in gate["rejection_codes"]


def test_gate_blocks_new_entries_when_existing_position_is_unprotected():
    held = [position("CINF", "10000", qty=86)]
    gate = evaluate_exposure_aware_trade_gate(
        candidate("KO", "core_dividend"),
        portfolio_value=Decimal("100000"),
        positions=held,
        open_orders=[],
    )
    assert gate["allowed"] is False
    assert gate["blocking_unprotected_symbols"] == ["CINF"]
    assert "existing_positions_not_fully_protected" in gate["rejection_codes"]


def test_nested_oco_stop_leg_counts_as_protection():
    held = [position("BKNG", "9000", qty=51)]
    orders = [
        {
            "symbol": "BKNG",
            "side": "sell",
            "type": "limit",
            "qty": 51,
            "limit_price": "192",
            "status": "accepted",
            "legs": [stop("BKNG", 51, status="held")],
        }
    ]
    snapshot = build_exposure_snapshot(
        portfolio_value=Decimal("100000"),
        positions=held,
        open_orders=orders,
    )
    assert snapshot["unprotected_positions"] == []
    assert snapshot["protection_by_symbol"]["BKNG"]["fully_stop_protected"] is True


def test_pending_buy_order_reduces_bucket_and_symbol_capacity():
    orders = [
        {
            "symbol": "NEW",
            "strategy_bucket": "value_rebound",
            "side": "buy",
            "type": "limit",
            "qty": 20,
            "limit_price": "100",
            "status": "pending_cancel",
        }
    ]
    gate = evaluate_exposure_aware_trade_gate(
        candidate(),
        portfolio_value=Decimal("100000"),
        positions=[],
        open_orders=orders,
    )
    assert gate["bucket_remaining_capacity"] == 28000.0
    assert gate["symbol_remaining_capacity"] == 5000.0
    assert gate["maximum_order_value"] == 5000.0


def test_gate_blocks_unhealthy_sync_and_stale_snapshot():
    gate = evaluate_exposure_aware_trade_gate(
        candidate(),
        portfolio_value=Decimal("100000"),
        positions=[],
        open_orders=[],
        database_sync_ok=False,
        snapshot_age_seconds=120,
        max_snapshot_age_seconds=60,
    )
    assert gate["allowed"] is False
    assert gate["rejection_codes"] == [
        "database_sync_unhealthy",
        "broker_snapshot_stale",
    ]


def test_batch_filter_returns_auditable_rejections():
    result = filter_candidates_with_exposure_gate(
        selected_positions=[
            candidate("KO", "core_dividend"),
            candidate("ACGL", "value_rebound"),
        ],
        position_analysis_payloads=[
            {"ticker": "KO"},
            {"ticker": "ACGL"},
        ],
        portfolio_value=Decimal("100000"),
        positions=[position("CINF", "10000", qty=86)],
        open_orders=[],
    )
    assert result["summary"]["allowed_count"] == 0
    assert result["summary"]["rejected_count"] == 2
    assert result["summary"]["global_new_entry_blocked"] is True
    assert all(
        "existing_positions_not_fully_protected" in row["rejection_codes"]
        for row in result["rejected"]
    )

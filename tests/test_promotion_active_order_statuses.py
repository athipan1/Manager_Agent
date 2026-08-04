from app.services.promotion_paper_observer import _active_orders


def test_database_synced_active_order_statuses_are_reconciled():
    rows = [
        {"symbol": "AAPL", "order_id": "placed-1", "status": "placed"},
        {"symbol": "MSFT", "order_id": "pending-1", "status": "pending"},
        {"symbol": "NVDA", "order_id": "filled-1", "status": "filled"},
    ]

    active = _active_orders(rows)

    assert [row["order_id"] for row in active] == ["placed-1", "pending-1"]

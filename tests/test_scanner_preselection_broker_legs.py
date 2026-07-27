from decimal import Decimal

from app.services.exposure_aware_trade_gate import build_exposure_snapshot
from app.workflows.scanner_preselection_workflow import _verified_database_context


def test_verified_context_restores_oco_stop_legs_from_verified_snapshot():
    sync_status = {
        "latest_snapshot": {
            "open_orders": [
                {
                    "id": "parent-order",
                    "symbol": "ACGL",
                    "side": "sell",
                    "type": "limit",
                    "status": "pending_cancel",
                    "legs": [
                        {
                            "id": "stop-leg",
                            "symbol": "ACGL",
                            "side": "sell",
                            "type": "stop",
                            "order_type": "stop",
                            "status": "held",
                            "qty": "151",
                            "stop_price": "97.02",
                            "legs": None,
                        }
                    ],
                }
            ]
        },
        "database": {
            "account": {"cash_balance": "87975.91"},
            "positions": [
                {
                    "symbol": "ACGL",
                    "quantity": 151,
                    "current_market_price": "103.36",
                    "market_value": "15607.36",
                    "strategy_bucket": "value_rebound",
                }
            ],
            "open_orders": [
                {
                    "trade_id": "broker:parent-order",
                    "broker_order_id": "parent-order",
                    "symbol": "ACGL",
                    "side": "sell",
                    "order_type": "limit",
                    "quantity": 151,
                    "price": "109.14",
                    "status": "placed",
                    "broker_status": "pending_cancel",
                    "strategy_bucket": "value_rebound",
                }
            ],
        },
    }

    cash, positions, orders = _verified_database_context(sync_status)
    exposure = build_exposure_snapshot(
        portfolio_value=cash + Decimal("15607.36"),
        positions=positions,
        open_orders=orders,
    )

    assert orders[0]["strategy_bucket"] == "value_rebound"
    assert orders[0]["legs"][0]["id"] == "stop-leg"
    assert exposure["summary"]["flattened_order_count"] == 2
    assert exposure["protection_by_symbol"]["ACGL"] == {
        "position_qty": 151.0,
        "stop_covered_qty": 151.0,
        "unprotected_stop_qty": 0.0,
        "fully_stop_protected": True,
    }
    assert exposure["unprotected_positions"] == []


def test_verified_context_does_not_invent_legs_without_snapshot_match():
    sync_status = {
        "latest_snapshot": {"open_orders": [{"id": "different-order"}]},
        "database": {
            "account": {"cash_balance": "100"},
            "positions": [],
            "open_orders": [
                {
                    "broker_order_id": "database-order",
                    "symbol": "AAPL",
                    "side": "buy",
                    "quantity": 1,
                    "order_type": "limit",
                    "status": "placed",
                }
            ],
        },
    }

    _, _, orders = _verified_database_context(sync_status)

    assert "legs" not in orders[0]

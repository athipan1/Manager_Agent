from scripts.check_paper_protection_window import (
    _normalize_alpaca_base_url,
    attention_symbols,
    pending_cancel_orders,
    should_defer_for_closed_market,
)


def diagnostics_with_pending_orders():
    return {
        "positions": [
            {
                "symbol": "ACGL",
                "protection_status": "partially_protected",
                "open_orders": [
                    {
                        "id": "order-acgl",
                        "symbol": "ACGL",
                        "status": "pending_cancel",
                        "qty": "54",
                        "type": "limit",
                    },
                    {
                        "id": "order-acgl",
                        "symbol": "ACGL",
                        "status": "pending_cancel",
                        "qty": "54",
                        "type": "limit",
                    },
                ],
            },
            {
                "symbol": "ADBE",
                "protection_status": "stop_only",
                "open_orders": [
                    {
                        "id": "order-adbe",
                        "symbol": "ADBE",
                        "status": "pending_cancel",
                        "qty": "36",
                        "type": "stop",
                    }
                ],
            },
            {
                "symbol": "BKNG",
                "protection_status": "bracket_protected",
                "open_orders": [
                    {
                        "id": "order-bkng",
                        "symbol": "BKNG",
                        "status": "new",
                        "qty": "9",
                        "type": "limit",
                    }
                ],
            },
        ]
    }


def test_closed_market_defers_when_every_attention_symbol_is_pending_cancel():
    diagnostics = diagnostics_with_pending_orders()

    assert should_defer_for_closed_market(
        diagnostics,
        {"is_open": False, "next_open": "2026-07-13T13:30:00Z"},
    ) is True


def test_open_market_never_defers_pending_cancel_reconciliation():
    diagnostics = diagnostics_with_pending_orders()

    assert should_defer_for_closed_market(
        diagnostics,
        {"is_open": True},
    ) is False


def test_unprotected_symbol_without_pending_order_prevents_defer():
    diagnostics = diagnostics_with_pending_orders()
    diagnostics["positions"].append(
        {
            "symbol": "CINF",
            "protection_status": "unprotected",
            "open_orders": [],
        }
    )

    assert attention_symbols(diagnostics) == {"ACGL", "ADBE", "CINF"}
    assert should_defer_for_closed_market(
        diagnostics,
        {"is_open": False},
    ) is False


def test_pending_cancel_orders_are_deduplicated_by_broker_order_id():
    pending = pending_cancel_orders(diagnostics_with_pending_orders())

    assert pending == [
        {
            "symbol": "ACGL",
            "broker_order_id": "order-acgl",
            "status": "pending_cancel",
            "qty": "54",
            "order_class": None,
            "type": "limit",
            "submitted_at": None,
            "created_at": None,
        },
        {
            "symbol": "ADBE",
            "broker_order_id": "order-adbe",
            "status": "pending_cancel",
            "qty": "36",
            "order_class": None,
            "type": "stop",
            "submitted_at": None,
            "created_at": None,
        },
    ]


def test_normalize_alpaca_base_url_removes_v2_and_trailing_slash():
    assert (
        _normalize_alpaca_base_url("https://paper-api.alpaca.markets/v2/")
        == "https://paper-api.alpaca.markets"
    )

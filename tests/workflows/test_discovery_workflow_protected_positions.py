from decimal import Decimal
from types import SimpleNamespace

from app.workflows.discovery_workflow import (
    protected_position_symbols,
    skip_protected_portfolio_payloads,
)


def test_protected_position_symbols_requires_position_and_open_sell_stop():
    positions = [
        SimpleNamespace(symbol="ACGL", quantity=82, average_cost=Decimal("96.79")),
        SimpleNamespace(symbol="ADBE", quantity=52, average_cost=Decimal("198.76")),
        SimpleNamespace(symbol="MSFT", quantity=10, average_cost=Decimal("420")),
    ]
    orders = [
        {"symbol": "ACGL", "side": "sell", "order_type": "stop", "status": "placed", "quantity": 82},
        {"symbol": "ADBE", "side": "buy", "order_type": "limit", "status": "placed", "quantity": 8},
        {"symbol": "MSFT", "side": "sell", "order_type": "stop", "status": "cancelled", "quantity": 10},
    ]

    assert protected_position_symbols(positions, orders) == {"ACGL"}


def test_skip_protected_portfolio_payloads_removes_only_already_protected_symbols():
    selected_positions = [
        {"symbol": "ACGL", "strategy_bucket": "value_rebound", "target_weight": 0.3, "target_value": 36614.46},
        {"symbol": "ADBE", "strategy_bucket": "core_dividend", "target_weight": 0.5, "target_value": 61024.11},
    ]
    payloads = [
        {"ticker": "ACGL", "strategy_bucket": "value_rebound"},
        {"ticker": "ADBE", "strategy_bucket": "core_dividend"},
    ]
    positions = [
        {"symbol": "ACGL", "qty": "82"},
        {"symbol": "ADBE", "qty": "52"},
    ]
    orders = [
        {"symbol": "ACGL", "side": "sell", "type": "stop", "status": "new", "qty": "82", "stop_price": "92.94"},
        {"symbol": "ADBE", "side": "sell", "type": "stop", "status": "cancelled", "qty": "52", "stop_price": "190.12"},
    ]

    risk_payloads, skipped = skip_protected_portfolio_payloads(
        selected_positions=selected_positions,
        position_analysis_payloads=payloads,
        positions=positions,
        orders=orders,
    )

    assert risk_payloads == [{"ticker": "ADBE", "strategy_bucket": "core_dividend"}]
    assert skipped == [
        {
            "symbol": "ACGL",
            "reason": "position already has an open protective broker order",
            "strategy_bucket": "value_rebound",
            "target_weight": 0.3,
            "target_value": 36614.46,
        }
    ]

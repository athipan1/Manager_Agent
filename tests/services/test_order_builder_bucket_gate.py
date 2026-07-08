import pytest

from app.services.order_builder import OrderBuildError, order_request_from_decision


def _decision(action="buy", **overrides):
    data = {
        "symbol": "XYZ",
        "action": action,
        "position_size": 2,
        "entry_price": 100,
        "risk_approval_id": "risk-xyz",
        "guard_plan": {
            "symbol": "XYZ",
            "side": "sell" if action == "buy" else "buy",
            "quantity": 2,
            "trigger_price": 95 if action == "buy" else 105,
            "take_profit_price": 110 if action == "buy" else 90,
        },
    }
    data.update(overrides)
    return data


def test_buy_with_unassigned_bucket_is_blocked():
    with pytest.raises(OrderBuildError, match="strategy_bucket must be classified"):
        order_request_from_decision(
            _decision("buy"),
            account_id=1,
            client_order_id_factory=lambda: "buy-unassigned",
        )


def test_risk_reducing_sell_with_unassigned_bucket_is_allowed():
    order = order_request_from_decision(
        _decision("sell"),
        account_id=1,
        client_order_id_factory=lambda: "sell-unassigned",
    )

    assert order.side == "sell"
    assert order.strategy_bucket == "unassigned"


def test_buy_with_unknown_bucket_is_rejected():
    with pytest.raises(OrderBuildError, match="unsupported strategy_bucket"):
        order_request_from_decision(
            _decision("buy", strategy_bucket="ticker_specific_bucket"),
            account_id=1,
            client_order_id_factory=lambda: "buy-invalid",
        )


def test_buy_with_classified_bucket_is_allowed():
    order = order_request_from_decision(
        _decision("buy", strategy_bucket="value_rebound"),
        account_id=1,
        client_order_id_factory=lambda: "buy-classified",
    )

    assert order.side == "buy"
    assert order.strategy_bucket == "value_rebound"

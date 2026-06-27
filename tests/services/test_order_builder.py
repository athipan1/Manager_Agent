from app.services.order_builder import (
    guard_plan_for_execution,
    order_request_from_decision,
    order_request_from_trade_plan_decision,
    side_from_action,
)


def test_side_from_action_maps_buy_variants_to_buy():
    assert side_from_action("buy") == "buy"
    assert side_from_action("strong_buy") == "buy"
    assert side_from_action("STRONG_BUY") == "buy"


def test_side_from_action_defaults_to_sell_for_non_buy_actions():
    assert side_from_action("sell") == "sell"
    assert side_from_action("strong_sell") == "sell"
    assert side_from_action("hold") == "sell"
    assert side_from_action("") == "sell"


def test_guard_plan_for_execution_uses_existing_guard_plan():
    guard_plan = {"source": "risk_agent", "stop_loss": 95.0}

    assert guard_plan_for_execution({"guard_plan": guard_plan}) is guard_plan


def test_guard_plan_for_execution_builds_default_guard_plan():
    decision = {"stop_loss": "95.5", "risk_amount": "12.25"}

    assert guard_plan_for_execution(decision) == {
        "source": "manager_portfolio_default_guard",
        "stop_loss": 95.5,
        "risk_amount": 12.25,
    }


def test_order_request_from_decision_builds_execution_contract():
    decision = {
        "symbol": "aapl",
        "action": "strong_buy",
        "position_size": 3,
        "entry_price": "123.45",
        "risk_approval_id": "risk-123",
        "stop_loss": 120.0,
        "risk_amount": 10.0,
        "stock_risk_context": {"strategy_bucket": "value_rebound"},
    }

    order = order_request_from_decision(
        decision,
        account_id=7,
        client_order_id_factory=lambda: "client-1",
    )

    assert order.symbol == "AAPL"
    assert order.side == "buy"
    assert order.order_type == "market"
    assert order.quantity == 3
    assert order.final_quantity == 3
    assert order.price == 123.45
    assert order.account_id == "7"
    assert order.client_order_id == "client-1"
    assert order.risk_approval_id == "risk-123"
    assert order.strategy_bucket == "value_rebound"
    assert order.guard_plan == {
        "source": "manager_portfolio_default_guard",
        "stop_loss": 120.0,
        "risk_amount": 10.0,
    }


def test_order_request_from_decision_uses_final_quantity_when_position_size_missing():
    decision = {
        "symbol": "MSFT",
        "action": "sell",
        "final_quantity": 4,
        "entry_price": None,
        "risk_approval_id": "risk-456",
    }

    order = order_request_from_decision(
        decision,
        account_id="paper-account",
        client_order_id_factory=lambda: "client-2",
    )

    assert order.symbol == "MSFT"
    assert order.side == "sell"
    assert order.quantity == 4
    assert order.final_quantity == 4
    assert order.price == 0.0
    assert order.account_id == "paper-account"
    assert order.strategy_bucket == "unassigned"


def test_order_request_from_decision_prefers_trade_plan_snapshot():
    decision = {
        "risk_approval_id": "risk-789",
        "symbol": "SHOULD_NOT_USE",
        "action": "sell",
        "position_size": 99,
        "trade_plan": {
            "plan_id": "plan-789",
            "correlation_id": "corr-789",
            "source": "single_analysis",
            "status": "risk_approved",
            "account_id": "1",
            "symbol": "aapl",
            "side": "buy",
            "order_type": "market",
            "entry_price": 150.0,
            "quantity": 5,
            "final_quantity": 5,
            "time_in_force": "GTC",
            "strategy": "trend_pullback",
            "strategy_bucket": "value_rebound",
            "final_verdict": "buy",
            "confidence_score": 0.71,
            "risk": {
                "max_loss_amount": 25,
                "max_loss_pct": 0.005,
            },
            "exit": {
                "stop_loss": 145,
                "take_profit": 160,
            },
            "risk_approval_id": "risk-789",
            "manual_approval_required": False,
            "dry_run": False,
            "reasons": [],
            "guard_plan": {"source": "trade_plan_guard", "stop_loss": 145},
            "metadata": {},
        },
    }

    order = order_request_from_decision(decision, account_id="ignored")

    assert order.client_order_id == "plan-789"
    assert order.account_id == "1"
    assert order.symbol == "AAPL"
    assert order.side == "buy"
    assert order.quantity == 5
    assert order.price == 150.0
    assert order.risk_approval_id == "risk-789"
    assert order.strategy_bucket == "value_rebound"
    assert order.guard_plan == {"source": "trade_plan_guard", "stop_loss": 145}
    assert order.protective_exit["stop_loss"] == 145
    assert decision["order_source"] == "trade_plan"


def test_trade_plan_order_builder_falls_back_when_snapshot_missing_approval():
    decision = {
        "trade_plan": {
            "plan_id": "plan-no-risk",
            "correlation_id": "corr-no-risk",
            "account_id": "1",
            "symbol": "AAPL",
            "side": "buy",
            "entry_price": 150,
            "quantity": 5,
            "final_verdict": "buy",
            "confidence_score": 0.71,
            "risk": {
                "max_loss_amount": 25,
                "max_loss_pct": 0.005,
            },
            "exit": {"stop_loss": 145},
        }
    }

    assert order_request_from_trade_plan_decision(decision) is None
    assert "risk_approval_id is required" in decision["trade_plan_order_error"]

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.workflows.risk_workflow import (
    approved_trades,
    evaluate_portfolio_risk,
    evaluate_single_trade_risk,
    is_tradeable_verdict,
    rejected_trade_decision,
)


class Position:
    def __init__(self, symbol="AAPL", quantity=1, average_cost=Decimal("90"), current_market_price=Decimal("100")):
        self.symbol = symbol
        self.quantity = quantity
        self.average_cost = average_cost
        self.current_market_price = current_market_price


def test_is_tradeable_verdict():
    assert is_tradeable_verdict("buy") is True
    assert is_tradeable_verdict("strong_buy") is True
    assert is_tradeable_verdict("sell") is True
    assert is_tradeable_verdict("strong_sell") is True
    assert is_tradeable_verdict("hold") is False
    assert is_tradeable_verdict(None) is False


def test_rejected_trade_decision_shape():
    decision = rejected_trade_decision(
        symbol="AAPL",
        action="buy",
        reason="guard rejected",
        session_risk_context={"trades_today": 1},
    )

    assert decision == {
        "approved": False,
        "reason": "guard rejected",
        "symbol": "AAPL",
        "action": "buy",
        "position_size": 0,
        "session_risk_context": {"trades_today": 1},
    }


def test_approved_trades_filters_only_approved_decisions():
    decisions = [
        {"symbol": "AAPL", "approved": True},
        {"symbol": "MSFT", "approved": False},
        {"symbol": "NVDA", "approved": True},
    ]

    assert approved_trades(decisions) == [
        {"symbol": "AAPL", "approved": True},
        {"symbol": "NVDA", "approved": True},
    ]


def test_evaluate_single_trade_risk_rejects_stock_guard_failure(monkeypatch):
    def fake_validate_trade_action(*args, **kwargs):
        from app.stock_guard import StockGuardError

        raise StockGuardError("guard rejected")

    monkeypatch.setattr("app.workflows.risk_workflow.validate_trade_action", fake_validate_trade_action)

    decision = evaluate_single_trade_risk(
        ticker="AAPL",
        final_verdict="buy",
        analysis_result={},
        balance=SimpleNamespace(cash_balance=Decimal("10000")),
        positions=[],
        context_value=Decimal("0"),
        session_context={"trades_today": 1},
        correlation_id="cid",
    )

    assert decision["approved"] is False
    assert decision["reason"] == "guard rejected"
    assert decision["risk_approval_id"] == "risk-cid-AAPL"


def test_evaluate_single_trade_risk_calls_assess_trade(monkeypatch):
    calls = []

    def fake_validate_trade_action(*args, **kwargs):
        return None

    def fake_assess_trade(**kwargs):
        calls.append(kwargs)
        return {"approved": True, "symbol": kwargs["symbol"], "position_size": 2}

    monkeypatch.setattr("app.workflows.risk_workflow.validate_trade_action", fake_validate_trade_action)
    monkeypatch.setattr("app.workflows.risk_workflow.assess_trade", fake_assess_trade)
    monkeypatch.setattr("app.workflows.risk_workflow.config_manager.get", lambda key, default=None: {
        "RISK_PER_TRADE": "0.01",
        "STOP_LOSS_PERCENTAGE": "0.03",
        "ENABLE_TECHNICAL_STOP": True,
        "MAX_POSITION_PERCENTAGE": "0.2",
    }.get(key, default))

    analysis_result = {
        "raw_data": {
            "technical": {
                "data": {
                    "current_price": "100",
                    "indicators": {"stop_loss": "95"},
                }
            }
        }
    }

    decision = evaluate_single_trade_risk(
        ticker="AAPL",
        final_verdict="buy",
        analysis_result=analysis_result,
        balance=SimpleNamespace(cash_balance=Decimal("10000")),
        positions=[Position()],
        context_value=Decimal("20"),
        session_context={"trades_today": 1},
        correlation_id="cid",
    )

    assert decision["approved"] is True
    assert decision["risk_approval_id"] == "risk-cid-AAPL"
    assert calls[0]["symbol"] == "AAPL"
    assert calls[0]["entry_price"] == Decimal("100.0")
    assert calls[0]["technical_stop_loss"] == Decimal("95")
    assert calls[0]["open_orders_exposure"] == Decimal("20")
    assert calls[0]["current_symbol_exposure"] == Decimal("100")
    assert calls[0]["correlation_id"] == "cid"


def test_evaluate_portfolio_risk_calls_assess_portfolio_and_adds_approval_ids(monkeypatch):
    calls = []

    def fake_assess_portfolio_trades(**kwargs):
        calls.append(kwargs)
        return [
            {"approved": True, "symbol": "AAPL", "position_size": 1},
            {"approved": False, "symbol": "MSFT", "position_size": 0},
        ]

    monkeypatch.setattr("app.workflows.risk_workflow.assess_portfolio_trades", fake_assess_portfolio_trades)
    monkeypatch.setattr("app.workflows.risk_workflow.config_manager.get", lambda key, default=None: {
        "PER_REQUEST_RISK_BUDGET": "0.1",
        "MAX_TOTAL_EXPOSURE": "0.8",
        "RISK_PER_TRADE": "0.01",
        "STOP_LOSS_PERCENTAGE": "0.03",
        "ENABLE_TECHNICAL_STOP": True,
        "MAX_POSITION_PERCENTAGE": "0.2",
        "MIN_POSITION_VALUE": "500",
    }.get(key, default))

    decisions = evaluate_portfolio_risk(
        analysis_results=[{"ticker": "AAPL"}],
        cash_balance=Decimal("10000"),
        existing_positions=[Position()],
        context_value=Decimal("30"),
        session_context={"trades_today": 1},
        correlation_id="cid",
    )

    assert decisions[0]["risk_approval_id"] == "risk-cid-AAPL"
    assert decisions[1]["risk_approval_id"] == "risk-cid-MSFT"
    assert calls[0]["analysis_results"] == [{"ticker": "AAPL"}]
    assert calls[0]["cash_balance"] == Decimal("10000")
    assert calls[0]["open_orders_exposure"] == Decimal("30")
    assert calls[0]["session_risk_context"] == {"trades_today": 1}
    assert calls[0]["correlation_id"] == "cid"

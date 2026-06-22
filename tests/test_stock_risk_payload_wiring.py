from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from app.risk_manager import assess_trade
from app.portfolio_risk_manager import assess_portfolio_trades
from app.models import ReportDetail, ReportDetails


def approved_response(quantity=10, symbol="AAPL"):
    return {
        "status": "approved",
        "data": {
            "approved": True,
            "final_quantity": quantity,
            "approved_quantity": quantity,
            "guard_plan": {"symbol": symbol, "quantity": quantity, "trigger_price": 90.0},
            "violations": [],
            "warnings": [],
        },
        "error": None,
    }


@patch("app.risk_manager.config.TRADING_ENABLED", True)
@patch("app.risk_manager.config.TRADING_MODE", "PAPER")
@patch("app.risk_manager.evaluate_risk")
def test_assess_trade_passes_stock_risk_context_to_payload(mock_evaluate_risk):
    mock_evaluate_risk.return_value = approved_response(quantity=10)

    decision = assess_trade(
        portfolio_value=Decimal("100000"),
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.05"),
        enable_technical_stop=False,
        max_position_pct=Decimal("0.20"),
        symbol="AAPL",
        action="buy",
        entry_price=Decimal("100"),
        current_position_size=3,
        stock_risk_context={
            "asset_class": "stock",
            "sector": "Technology",
            "owned_quantity": 3,
            "current_sector_exposure": 2500,
        },
    )

    assert decision["approved"] is True
    assert decision["stock_risk_context"]["sector"] == "Technology"
    payload = mock_evaluate_risk.call_args.args[0]
    assert payload["asset_class"] == "stock"
    assert payload["sector"] == "Technology"
    assert payload["owned_quantity"] == 3
    assert payload["current_sector_exposure"] == 2500


@patch("app.risk_manager.config.TRADING_ENABLED", True)
@patch("app.risk_manager.config.TRADING_MODE", "PAPER")
@patch("app.risk_manager.evaluate_risk")
def test_assess_trade_defaults_owned_quantity_from_current_position_size(mock_evaluate_risk):
    mock_evaluate_risk.return_value = approved_response(quantity=5)

    assess_trade(
        portfolio_value=Decimal("100000"),
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.05"),
        enable_technical_stop=False,
        max_position_pct=Decimal("0.20"),
        symbol="AAPL",
        action="sell",
        entry_price=Decimal("100"),
        current_position_size=5,
    )

    payload = mock_evaluate_risk.call_args.args[0]
    assert payload["asset_class"] == "stock"
    assert payload["owned_quantity"] == 5.0
    assert payload["current_sector_exposure"] == 0.0


@patch("app.risk_manager.config.TRADING_ENABLED", True)
@patch("app.risk_manager.config.TRADING_MODE", "PAPER")
@patch("app.risk_manager.evaluate_risk")
def test_portfolio_risk_manager_builds_stock_context_from_fundamental_sector(mock_evaluate_risk):
    mock_evaluate_risk.return_value = approved_response(quantity=5, symbol="AAPL")
    positions = [
        SimpleNamespace(symbol="MSFT", quantity=5, average_cost=Decimal("200"), current_market_price=None, metadata={"sector": "Technology"}),
        SimpleNamespace(symbol="JNJ", quantity=5, average_cost=Decimal("50"), current_market_price=None, metadata={"sector": "Healthcare"}),
    ]
    analysis_results = [
        {
            "ticker": "AAPL",
            "final_verdict": "buy",
            "details": ReportDetails(
                technical=ReportDetail(action="buy", score=0.9, reason=""),
                fundamental=ReportDetail(action="buy", score=0.8, reason=""),
            ),
            "raw_data": {
                "technical": {"data": {"current_price": 100, "indicators": {"stop_loss": 95}}},
                "fundamental": {"data": {"current_price": 100, "sector": "Technology"}},
            },
        }
    ]

    decisions = assess_portfolio_trades(
        analysis_results=analysis_results,
        cash_balance=Decimal("100000"),
        existing_positions=positions,
        per_request_risk_budget=Decimal("0.05"),
        max_total_exposure=Decimal("0.80"),
        risk_per_trade=Decimal("0.01"),
        fixed_stop_loss_pct=Decimal("0.05"),
        enable_technical_stop=True,
        max_position_pct=Decimal("0.20"),
        min_position_value=Decimal("500"),
    )

    assert decisions[0]["approved"] is True
    payload = mock_evaluate_risk.call_args.args[0]
    assert payload["asset_class"] == "stock"
    assert payload["sector"] == "Technology"
    assert payload["owned_quantity"] == 0.0
    assert payload["current_sector_exposure"] == 1000.0

from decimal import Decimal
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import AccountBalance, Position, ReportDetail, ReportDetails

client = TestClient(app)


def analysis_result():
    return {
        "ticker": "AAPL",
        "final_verdict": "buy",
        "status": "complete",
        "details": ReportDetails(
            technical=ReportDetail(action="buy", score=0.9, reason=""),
            fundamental=ReportDetail(action="buy", score=0.8, reason=""),
        ),
        "raw_data": {
            "technical": {
                "status": "success",
                "data": {
                    "action": "buy",
                    "confidence_score": 0.9,
                    "current_price": 100.0,
                    "indicators": {"stop_loss": 90.0},
                },
            },
            "fundamental": {
                "status": "success",
                "data": {"action": "buy", "confidence_score": 0.8, "current_price": 100.0},
            },
        },
    }


def config_value(key, default=None):
    values = {
        "DEFAULT_ACCOUNT_ID": 1,
        "RISK_PER_TRADE": "0.01",
        "STOP_LOSS_PERCENTAGE": "0.10",
        "MAX_POSITION_PERCENTAGE": "0.20",
        "ENABLE_TECHNICAL_STOP": True,
    }
    return values.get(key, default)


@patch("app.main.config.TRADING_ENABLED", True)
@patch("app.main.config.TRADING_MODE", "PAPER")
@patch("app.main.config.APPLY_LEARNING_DELTAS", False)
@patch("app.main.config_manager")
@patch("app.main.LearningAgentClient", autospec=True)
@patch("app.main._execute_trade", new_callable=AsyncMock)
@patch("app.main.assess_trade")
@patch("app.main._analyze_single_asset", new_callable=AsyncMock)
@patch("app.main.DatabaseAgentClient", autospec=True)
def test_single_flow_calculates_context_from_database_rows(
    mock_db_class,
    mock_analyze,
    mock_assess,
    mock_exec,
    mock_learning_class,
    mock_config,
):
    mock_config.get.side_effect = config_value
    db = mock_db_class.return_value.__aenter__.return_value
    db.get_account_balance.return_value = AccountBalance(cash_balance=Decimal("100000"))
    db.get_positions.return_value = [Position(symbol="AAPL", quantity=10, average_cost=Decimal("90"), current_market_price=Decimal("100"))]
    db.get_orders.return_value = [
        {"symbol": "AAPL", "status": "pending", "quantity": 3, "executed_quantity": 1, "price": 100},
        {"symbol": "AAPL", "status": "executed", "quantity": 5, "executed_quantity": 5, "price": 100},
    ]
    mock_analyze.return_value = analysis_result()
    mock_assess.return_value = {"approved": False, "reason": "test", "symbol": "AAPL", "action": "buy", "position_size": 0}
    learning = mock_learning_class.return_value
    learning.trigger_learning_cycle = AsyncMock(return_value=None)

    response = client.post("/analyze", json={"ticker": "AAPL"})

    assert response.status_code == 200
    payload = mock_assess.call_args.kwargs
    assert payload["open_orders_exposure"] == Decimal("200")
    assert payload["current_total_exposure"] == Decimal("1000")
    body = response.json()
    assert body["metadata"]["trading_mode"] == "PAPER"
    assert body["metadata"]["trading_enabled"] is True
    assert body["metadata"]["risk_context_loaded"] is True
    assert body["metadata"]["learning_delta_auto_apply_enabled"] is False

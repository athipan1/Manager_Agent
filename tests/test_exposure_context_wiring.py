import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import AccountBalance, Position, ReportDetail, ReportDetails
from app.contracts import StandardAgentResponse, StandardAgentData

client = TestClient(app)


def analysis_result(symbol="AAPL", verdict="buy", price=Decimal("100")):
    return {
        "ticker": symbol,
        "final_verdict": verdict,
        "status": "complete",
        "details": ReportDetails(
            technical=ReportDetail(action=verdict, score=0.9, reason=""),
            fundamental=ReportDetail(action=verdict, score=0.8, reason=""),
        ),
        "raw_data": {
            "technical": StandardAgentResponse(
                status="success",
                agent_type="technical",
                version="1.0",
                timestamp=datetime.datetime.now(),
                data=StandardAgentData(
                    action=verdict,
                    confidence_score=0.9,
                    current_price=float(price),
                    indicators={"stop_loss": float(price * Decimal("0.9"))},
                ),
            ),
            "fundamental": StandardAgentResponse(
                status="success",
                agent_type="fundamental",
                version="1.0",
                timestamp=datetime.datetime.now(),
                data=StandardAgentData(action=verdict, confidence_score=0.8, current_price=float(price)),
            ),
        },
    }


def configure_db(mock_db_client_class, rows=None):
    data_rows = rows if rows is not None else [
        {"symbol": "AAPL", "status": "pending", "quantity": 3, "executed_quantity": 1, "price": 100},
        {"symbol": "MSFT", "status": "executed", "quantity": 5, "executed_quantity": 5, "price": 200},
    ]
    db = mock_db_client_class.return_value.__aenter__.return_value
    db.get_account_balance.return_value = AccountBalance(cash_balance=Decimal("100000"))
    db.get_positions.return_value = [Position(symbol="AAPL", quantity=10, average_cost=Decimal("90"), current_market_price=Decimal("100"))]
    db._get.return_value = {"status": "success", "data": data_rows, "error": None}
    db.validate_standard_response.return_value = Mock(data=data_rows)
    return db


def config_value(key, default=None):
    values = {
        "DEFAULT_ACCOUNT_ID": 1,
        "RISK_PER_TRADE": "0.01",
        "STOP_LOSS_PERCENTAGE": "0.10",
        "MAX_POSITION_PERCENTAGE": "0.20",
        "ENABLE_TECHNICAL_STOP": True,
        "PER_REQUEST_RISK_BUDGET": "0.20",
        "MAX_TOTAL_EXPOSURE": "0.80",
        "MIN_POSITION_VALUE": "500",
    }
    return values.get(key, default)


@patch("app.main.config_manager")
@patch("app.main._execute_trade", new_callable=AsyncMock)
@patch("app.main.assess_trade")
@patch("app.main._analyze_single_asset", new_callable=AsyncMock)
@patch("app.main.DatabaseAgentClient", autospec=True)
def test_single_analyze_sends_context_value_to_risk(mock_db_class, mock_analyze, mock_assess, mock_exec, mock_config):
    mock_config.get.side_effect = config_value
    configure_db(mock_db_class)
    mock_analyze.return_value = analysis_result("AAPL", "buy")
    mock_assess.return_value = {"approved": False, "reason": "test", "symbol": "AAPL", "action": "buy", "position_size": 0}

    response = client.post("/analyze", json={"ticker": "AAPL"})

    assert response.status_code == 200
    assert mock_assess.call_args.kwargs["open_orders_exposure"] == Decimal("200")
    assert mock_assess.call_args.kwargs["current_symbol_exposure"] == Decimal("1000")
    assert mock_assess.call_args.kwargs["current_total_exposure"] == Decimal("1000")


@patch("app.main.config_manager")
@patch("app.main._execute_trade", new_callable=AsyncMock)
@patch("app.main.assess_portfolio_trades")
@patch("app.main._analyze_single_asset", new_callable=AsyncMock)
@patch("app.main.DatabaseAgentClient", autospec=True)
def test_multi_analyze_sends_context_value_to_portfolio_risk(mock_db_class, mock_analyze, mock_portfolio, mock_exec, mock_config):
    mock_config.get.side_effect = config_value
    configure_db(mock_db_class)
    mock_analyze.return_value = analysis_result("AAPL", "buy")
    mock_portfolio.return_value = []

    response = client.post("/analyze-multi", json={"tickers": ["AAPL"]})

    assert response.status_code == 200
    assert mock_portfolio.call_args.kwargs["open_orders_exposure"] == Decimal("200")


@patch("app.main.config_manager")
@patch("app.main._execute_trade", new_callable=AsyncMock)
@patch("app.main.assess_trade")
@patch("app.main._analyze_single_asset", new_callable=AsyncMock)
@patch("app.main.ScannerAgentClient", autospec=True)
@patch("app.main.DatabaseAgentClient", autospec=True)
def test_discover_analyze_trade_sends_context_value(mock_db_class, mock_scanner_class, mock_analyze, mock_assess, mock_exec, mock_config):
    mock_config.get.side_effect = config_value
    configure_db(mock_db_class)
    scanner = mock_scanner_class.return_value.__aenter__.return_value
    scanner.discover_best_fundamentals.return_value = StandardAgentResponse(
        status="success",
        agent_type="scanner",
        version="1.0",
        timestamp=datetime.datetime.now(),
        data={"candidates": [{"symbol": "AAPL", "candidate_score": 0.9}]},
    )
    mock_analyze.return_value = analysis_result("AAPL", "buy")
    mock_assess.return_value = {"approved": False, "reason": "test", "symbol": "AAPL", "action": "buy", "position_size": 0}

    response = client.post("/discover-analyze-trade", json={"execute": True, "min_final_score": 0.1})

    assert response.status_code == 200
    assert mock_assess.call_args.kwargs["open_orders_exposure"] == Decimal("200")


@patch("app.main.config.TRADING_MODE", "LIVE")
@patch("app.main.DatabaseAgentClient", autospec=True)
def test_live_mode_rejects_when_context_fetch_fails(mock_db_class):
    db = mock_db_class.return_value.__aenter__.return_value
    db.get_account_balance.return_value = AccountBalance(cash_balance=Decimal("100000"))
    db.get_positions.return_value = []
    db._get.side_effect = RuntimeError("context unavailable")

    response = client.post("/analyze", json={"ticker": "AAPL"})

    assert response.status_code == 503
    assert "Required portfolio context unavailable" in response.json()["detail"]

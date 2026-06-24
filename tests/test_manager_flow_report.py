import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import AccountBalance, ReportDetail, ReportDetails
from app.contracts import StandardAgentResponse

client = TestClient(app)


def result(symbol="AAPL"):
    return {
        "ticker": symbol,
        "final_verdict": "buy",
        "status": "complete",
        "details": ReportDetails(
            technical=ReportDetail(action="buy", score=0.9, reason=""),
            fundamental=ReportDetail(action="buy", score=0.8, reason=""),
        ),
        "raw_data": {
            "technical": {"status": "success", "data": {"action": "buy", "confidence_score": 0.9, "current_price": 100.0, "indicators": {"stop_loss": 90.0}}},
            "fundamental": {"status": "success", "data": {"action": "buy", "confidence_score": 0.8, "current_price": 100.0}},
        },
    }


def cfg(key, default=None):
    return {
        "DEFAULT_ACCOUNT_ID": 1,
        "RISK_PER_TRADE": "0.01",
        "STOP_LOSS_PERCENTAGE": "0.10",
        "MAX_POSITION_PERCENTAGE": "0.20",
        "ENABLE_TECHNICAL_STOP": True,
        "PER_REQUEST_RISK_BUDGET": "0.20",
        "MAX_TOTAL_EXPOSURE": "0.80",
        "MIN_POSITION_VALUE": "500",
    }.get(key, default)


@patch("app.main.config.TRADING_ENABLED", True)
@patch("app.main.config.TRADING_MODE", "PAPER")
@patch("app.main.config.APPLY_LEARNING_DELTAS", False)
@patch("app.main.config_manager")
@patch("app.main.LearningAgentClient", autospec=True)
@patch("app.main._execute_portfolio_batch", new_callable=AsyncMock)
@patch("app.main.assess_portfolio_trades")
@patch("app.main._analyze_single_asset", new_callable=AsyncMock)
@patch("app.main.ScannerAgentClient", autospec=True)
@patch("app.main.DatabaseAgentClient", autospec=True)
def test_discovery_flow_reports_approval_and_audit(mock_db, mock_scan, mock_analyze, mock_portfolio, mock_exec_batch, mock_learn, mock_cfg):
    mock_cfg.get.side_effect = cfg
    scanner = mock_scan.return_value.__aenter__.return_value
    scanner.discover_best_fundamentals.return_value = StandardAgentResponse(
        status="success",
        agent_type="scanner",
        version="1.0.0",
        timestamp=datetime.datetime.now(datetime.UTC),
        data={"candidates": [{"symbol": "AAPL", "candidate_score": 0.95}]},
    )
    db = mock_db.return_value.__aenter__.return_value
    db.get_account_balance.return_value = AccountBalance(cash_balance=Decimal("100000"))
    db.get_positions.return_value = []
    db.get_orders.return_value = [{"symbol": "AAPL", "status": "pending", "quantity": 2, "executed_quantity": 0, "price": 100}]
    db.save_signal = AsyncMock(return_value={})
    mock_analyze.return_value = result("AAPL")
    mock_portfolio.return_value = [
        {
            "approved": True,
            "reason": "ok",
            "symbol": "AAPL",
            "action": "buy",
            "entry_price": Decimal("100"),
            "position_size": 10,
            "risk_agent_response": {"data": {"approval_id": "approval-1"}},
            "guard_plan": {"symbol": "AAPL", "side": "sell", "quantity": 10, "trigger_price": 90},
            "risk_approval_id": "approval-1",
        }
    ]
    mock_exec_batch.return_value = {"status": "submitted", "created": [{"symbol": "AAPL", "risk_approval_id": "approval-1"}], "failed": []}
    learning = mock_learn.return_value
    learning.trigger_learning_cycle = AsyncMock(return_value=None)

    response = client.post("/discover-analyze-trade", json={"execute": True, "min_final_score": 0.1})

    assert response.status_code == 200
    body = response.json()
    data = body["data"]
    assert data["mode"] == "portfolio_allocation"
    assert data["selected_positions"][0]["symbol"] == "AAPL"
    assert data["risk_approvals"][0]["risk_approval_id"] == "approval-1"
    assert data["execution"]["status"] == "submitted"
    assert data["legacy"]["winner"]["symbol"] == "AAPL"
    assert data["legacy"]["risk_approval_id"] == "approval-1"
    assert mock_exec_batch.await_count == 1
    assert db.save_signal.await_count >= 2

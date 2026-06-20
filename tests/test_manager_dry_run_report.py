from decimal import Decimal
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app
from app.models import AccountBalance, ReportDetail, ReportDetails

client = TestClient(app)


def result():
    return {
        "ticker": "AAPL",
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
    }.get(key, default)


@patch("app.main.config.TRADING_ENABLED", True)
@patch("app.main.config.TRADING_MODE", "PAPER")
@patch("app.main.config_manager")
@patch("app.main._analyze_single_asset", new_callable=AsyncMock)
@patch("app.main.assess_trade")
@patch("app.main.DatabaseAgentClient", autospec=True)
def test_dry_run_analyze_returns_report_without_execution(mock_db, mock_gate, mock_analyze, mock_cfg):
    mock_cfg.get.side_effect = cfg
    db = mock_db.return_value.__aenter__.return_value
    db.get_account_balance.return_value = AccountBalance(cash_balance=Decimal("100000"))
    db.get_positions.return_value = []
    db.get_orders.return_value = []
    db.save_signal = AsyncMock(return_value={})
    mock_analyze.return_value = result()
    mock_gate.return_value = {"approved": True, "symbol": "AAPL", "action": "buy", "entry_price": Decimal("100"), "position_size": 10}

    response = client.post("/dry-run/analyze", json={"ticker": "AAPL"})

    assert response.status_code == 200
    body = response.json()
    assert body["metadata"]["dry_run"] is True
    assert body["data"]["dry_run"] is True
    assert body["data"]["execution"]["status"] == "dry_run"
    assert body["data"]["risk_approval_id"] is not None


def test_trade_replay_echoes_report_shape():
    response = client.post("/trade-replay", json={"symbol": "AAPL", "risk_context": {"open_orders_exposure": 25}, "trade_decision": {"risk_approval_id": "approval-1"}})

    assert response.status_code == 200
    body = response.json()
    assert body["metadata"]["dry_run"] is True
    assert body["data"]["flow"] == "trade_replay"
    assert body["data"]["risk_context"]["open_orders_exposure"] == 25.0

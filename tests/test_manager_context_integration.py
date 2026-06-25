import datetime

from fastapi.testclient import TestClient

from app.contracts import StandardAgentResponse
from app.main_modular import app

client = TestClient(app)


def context_response():
    return StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=datetime.datetime.now(datetime.UTC),
        data={
            "ticker": "AAPL",
            "risk_context": {
                "open_orders_exposure": 200.0,
                "current_total_exposure": 1000.0,
            },
            "trade_decision": {
                "approved": False,
                "reason": "test",
                "symbol": "AAPL",
                "action": "buy",
                "position_size": 0,
            },
        },
        metadata={
            "trading_mode": "PAPER",
            "trading_enabled": True,
            "risk_context_loaded": True,
            "learning_delta_auto_apply_enabled": False,
        },
    )


def test_single_flow_calculates_context_from_database_rows(monkeypatch):
    calls = []

    async def fake_run_single_analysis_flow(request, *, dry_run=False):
        calls.append({"request": request.model_dump(mode="json"), "dry_run": dry_run})
        return context_response()

    monkeypatch.setattr("app.routes.single_analysis.run_single_analysis_flow", fake_run_single_analysis_flow)

    response = client.post("/analyze", json={"ticker": "AAPL"})

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["risk_context"]["open_orders_exposure"] == 200.0
    assert body["data"]["risk_context"]["current_total_exposure"] == 1000.0
    assert body["metadata"]["trading_mode"] == "PAPER"
    assert body["metadata"]["trading_enabled"] is True
    assert body["metadata"]["risk_context_loaded"] is True
    assert body["metadata"]["learning_delta_auto_apply_enabled"] is False
    assert calls == [{"request": {"ticker": "AAPL", "period": "1mo", "account_id": None}, "dry_run": False}]

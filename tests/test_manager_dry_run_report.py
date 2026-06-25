import datetime

from fastapi.testclient import TestClient

from app.contracts import StandardAgentResponse
from app.main_modular import app

client = TestClient(app)


def dry_run_response():
    return StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=datetime.datetime.now(datetime.UTC),
        data={
            "dry_run": True,
            "execution": {"status": "dry_run"},
            "risk_approval_id": "dry-run-approval-1",
        },
        metadata={"dry_run": True},
    )


def test_dry_run_analyze_returns_report_without_execution(monkeypatch):
    calls = []

    async def fake_run_single_analysis_flow(request, *, dry_run=False):
        calls.append({"request": request.model_dump(mode="json"), "dry_run": dry_run})
        return dry_run_response()

    monkeypatch.setattr("app.routes.single_analysis.run_single_analysis_flow", fake_run_single_analysis_flow)

    response = client.post("/dry-run/analyze", json={"ticker": "AAPL"})

    assert response.status_code == 200
    body = response.json()
    assert body["metadata"]["dry_run"] is True
    assert body["data"]["dry_run"] is True
    assert body["data"]["execution"]["status"] == "dry_run"
    assert body["data"]["risk_approval_id"] is not None
    assert calls == [{"request": {"ticker": "AAPL", "period": "1mo", "account_id": None}, "dry_run": True}]


def test_trade_replay_echoes_report_shape():
    response = client.post(
        "/trade-replay",
        json={
            "symbol": "AAPL",
            "risk_context": {"open_orders_exposure": 25},
            "trade_decision": {"risk_approval_id": "approval-1"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["metadata"]["dry_run"] is True
    assert body["data"]["flow"] == "trade_replay"
    assert body["data"]["risk_context"]["open_orders_exposure"] == 25.0

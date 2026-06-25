import datetime

from fastapi.testclient import TestClient

from app.contracts import StandardAgentResponse
from app.main_modular import app

client = TestClient(app)


def discovery_response():
    return StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=datetime.datetime.now(datetime.UTC),
        data={
            "report_id": "discover-report-1",
            "flow": "discover_analyze_trade",
            "mode": "portfolio_allocation",
            "selected_positions": [{"symbol": "AAPL"}],
            "risk_approvals": [{"symbol": "AAPL", "risk_approval_id": "approval-1"}],
            "execution": {
                "status": "submitted",
                "created": [{"symbol": "AAPL", "risk_approval_id": "approval-1"}],
                "failed": [],
            },
            "legacy": {
                "winner": {"symbol": "AAPL"},
                "risk_approval_id": "approval-1",
            },
        },
    )


def test_discovery_flow_reports_approval_and_audit(monkeypatch):
    calls = []

    async def fake_run_discover_analyze_trade_flow(request):
        calls.append(request.model_dump(mode="json"))
        return discovery_response()

    monkeypatch.setattr(
        "app.routes.discovery.run_discover_analyze_trade_flow",
        fake_run_discover_analyze_trade_flow,
    )

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
    assert calls == [
        {
            "account_id": None,
            "max_universe": 1000,
            "top_n": 10,
            "exchange": "NASDAQ",
            "max_workers": 10,
            "min_final_score": 0.1,
            "execute": True,
        }
    ]

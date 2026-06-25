import datetime

from fastapi.testclient import TestClient

from app.contracts import StandardAgentResponse
from app.main_modular import app

client = TestClient(app)


def standard_analyze_response():
    return StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=datetime.datetime.now(datetime.UTC),
        data={
            "ticker": "AAPL",
            "final_verdict": "buy",
            "status": "complete",
        },
    )


def test_analyze_endpoint_standard_response(monkeypatch):
    calls = []

    async def fake_run_single_analysis_flow(request, *, dry_run=False):
        calls.append({"request": request.model_dump(mode="json"), "dry_run": dry_run})
        return standard_analyze_response()

    monkeypatch.setattr("app.routes.single_analysis.run_single_analysis_flow", fake_run_single_analysis_flow)

    response = client.post("/analyze", json={"ticker": "AAPL", "account_id": 1})

    assert response.status_code == 200
    json_response = response.json()
    assert json_response["status"] == "success"
    assert json_response["agent_type"] == "manager-agent"
    assert "data" in json_response
    assert json_response["data"]["ticker"] == "AAPL"
    assert "final_verdict" in json_response["data"]
    assert calls == [{"request": {"ticker": "AAPL", "period": "1mo", "account_id": 1}, "dry_run": False}]

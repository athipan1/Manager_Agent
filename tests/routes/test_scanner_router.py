import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.contracts import StandardAgentResponse
from app.routes.scanner import router


def make_app():
    app = FastAPI()
    app.include_router(router)
    return app


def success_response(payload):
    return StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=datetime.datetime.now(datetime.UTC),
        data={"request": payload},
    )


def test_scan_and_analyze_route_calls_scan_workflow(monkeypatch):
    calls = []

    async def fake_run_scan_and_analyze_flow(request):
        payload = request.model_dump(mode="json")
        calls.append(payload)
        return success_response(payload)

    monkeypatch.setattr(
        "app.routes.scanner.run_scan_and_analyze_flow",
        fake_run_scan_and_analyze_flow,
    )

    client = TestClient(make_app())
    response = client.post(
        "/scan-and-analyze",
        json={
            "symbols": ["AAPL", "MSFT"],
            "scan_type": "technical",
            "account_id": "acct-1",
            "max_candidates": 2,
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert calls == [
        {
            "symbols": ["AAPL", "MSFT"],
            "scan_type": "technical",
            "account_id": "acct-1",
            "max_candidates": 2,
        }
    ]

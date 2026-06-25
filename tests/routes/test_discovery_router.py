import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.contracts import StandardAgentResponse
from app.routes.discovery import router


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
        data={
            "flow": "discover_analyze_trade",
            "request": payload,
        },
    )


def test_discover_analyze_trade_route_calls_discovery_workflow(monkeypatch):
    calls = []

    async def fake_run_discover_analyze_trade_flow(request):
        payload = request.model_dump(mode="json")
        calls.append(payload)
        return success_response(payload)

    monkeypatch.setattr(
        "app.routes.discovery.run_discover_analyze_trade_flow",
        fake_run_discover_analyze_trade_flow,
    )

    client = TestClient(make_app())
    response = client.post(
        "/discover-analyze-trade",
        json={
            "account_id": "acct-1",
            "max_universe": 25,
            "top_n": 5,
            "exchange": "NASDAQ",
            "max_workers": 4,
            "min_final_score": 0.6,
            "execute": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["flow"] == "discover_analyze_trade"
    assert calls == [
        {
            "account_id": "acct-1",
            "max_universe": 25,
            "top_n": 5,
            "exchange": "NASDAQ",
            "max_workers": 4,
            "min_final_score": 0.6,
            "execute": False,
        }
    ]

import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.contracts import StandardAgentResponse
from app.routes.single_analysis import router


def make_app():
    app = FastAPI()
    app.include_router(router)
    return app


def success_response(*, dry_run):
    return StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=datetime.datetime.now(datetime.UTC),
        data={"dry_run": dry_run},
    )


def test_analyze_route_calls_single_analysis_workflow(monkeypatch):
    calls = []

    async def fake_run_single_analysis_flow(request, *, dry_run=False):
        calls.append({"ticker": request.ticker, "dry_run": dry_run})
        return success_response(dry_run=dry_run)

    monkeypatch.setattr("app.routes.single_analysis.run_single_analysis_flow", fake_run_single_analysis_flow)

    client = TestClient(make_app())
    response = client.post("/analyze", json={"ticker": "AAPL"})

    assert response.status_code == 200
    assert response.json()["data"] == {"dry_run": False}
    assert calls == [{"ticker": "AAPL", "dry_run": False}]


def test_dry_run_analyze_route_calls_single_analysis_workflow_with_dry_run(monkeypatch):
    calls = []

    async def fake_run_single_analysis_flow(request, *, dry_run=False):
        calls.append({"ticker": request.ticker, "dry_run": dry_run})
        return success_response(dry_run=dry_run)

    monkeypatch.setattr("app.routes.single_analysis.run_single_analysis_flow", fake_run_single_analysis_flow)

    client = TestClient(make_app())
    response = client.post("/dry-run/analyze", json={"ticker": "AAPL"})

    assert response.status_code == 200
    assert response.json()["data"] == {"dry_run": True}
    assert calls == [{"ticker": "AAPL", "dry_run": True}]

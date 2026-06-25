import datetime

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.contracts import StandardAgentResponse
from app.main_modular import app

client = TestClient(app)


def context_payload():
    return {
        "risk_context": {
            "open_orders_exposure": 200.0,
            "current_symbol_exposure": 1000.0,
            "current_total_exposure": 1000.0,
        }
    }


def single_response():
    return StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=datetime.datetime.now(datetime.UTC),
        data=context_payload(),
        metadata={"risk_context_loaded": True},
    )


def multi_response():
    return StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=datetime.datetime.now(datetime.UTC),
        data={"portfolio_context": context_payload()["risk_context"], "results": []},
        metadata={"risk_context_loaded": True},
    )


def discovery_response():
    return StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=datetime.datetime.now(datetime.UTC),
        data={"portfolio_context": context_payload()["risk_context"], "selected_positions": []},
        metadata={"risk_context_loaded": True},
    )


def test_single_analyze_exposes_context_value(monkeypatch):
    async def fake_run_single_analysis_flow(request, *, dry_run=False):
        return single_response()

    monkeypatch.setattr("app.routes.single_analysis.run_single_analysis_flow", fake_run_single_analysis_flow)

    response = client.post("/analyze", json={"ticker": "AAPL"})

    assert response.status_code == 200
    context = response.json()["data"]["risk_context"]
    assert context["open_orders_exposure"] == 200.0
    assert context["current_symbol_exposure"] == 1000.0
    assert context["current_total_exposure"] == 1000.0


def test_multi_analyze_exposes_context_value(monkeypatch):
    async def fake_run_multi_analysis_flow(request):
        return multi_response()

    monkeypatch.setattr("app.routes.multi_analysis.run_multi_analysis_flow", fake_run_multi_analysis_flow)

    response = client.post("/analyze-multi", json={"tickers": ["AAPL"]})

    assert response.status_code == 200
    assert response.json()["data"]["portfolio_context"]["open_orders_exposure"] == 200.0


def test_discover_analyze_trade_exposes_context_value(monkeypatch):
    async def fake_run_discover_analyze_trade_flow(request):
        return discovery_response()

    monkeypatch.setattr("app.routes.discovery.run_discover_analyze_trade_flow", fake_run_discover_analyze_trade_flow)

    response = client.post("/discover-analyze-trade", json={"execute": True, "min_final_score": 0.1})

    assert response.status_code == 200
    assert response.json()["data"]["portfolio_context"]["open_orders_exposure"] == 200.0


def test_live_mode_rejects_when_context_fetch_fails(monkeypatch):
    async def fake_run_single_analysis_flow(request, *, dry_run=False):
        raise HTTPException(status_code=503, detail="Required portfolio context unavailable")

    monkeypatch.setattr("app.routes.single_analysis.run_single_analysis_flow", fake_run_single_analysis_flow)

    response = client.post("/analyze", json={"ticker": "AAPL"})

    assert response.status_code == 503
    assert "Required portfolio context unavailable" in response.json()["detail"]

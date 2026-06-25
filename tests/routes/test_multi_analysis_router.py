import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.contracts import StandardAgentResponse
from app.models import (
    AssetResult,
    ExecutionResult,
    ExecutionSummary,
    AnalysisResult,
    MultiOrchestratorResponse,
    ReportDetails,
)
from app.routes.multi_analysis import router


def make_app():
    app = FastAPI()
    app.include_router(router)
    return app


def success_response(tickers):
    results = [
        AssetResult(
            analysis=AnalysisResult(
                ticker=ticker,
                final_verdict="hold",
                status="complete",
                details=ReportDetails(technical=None, fundamental=None),
            ),
            execution=ExecutionResult(status="rejected", reason="hold"),
        )
        for ticker in tickers
    ]
    return StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=datetime.datetime.now(datetime.UTC),
        data=MultiOrchestratorResponse(
            multi_report_id="report-1",
            timestamp=datetime.datetime.now(datetime.UTC),
            execution_summary=ExecutionSummary(
                total_trades_approved=0,
                total_trades_executed=0,
                total_trades_failed=0,
            ),
            results=results,
        ),
    )


def test_analyze_multi_route_calls_multi_analysis_workflow(monkeypatch):
    calls = []

    async def fake_run_multi_analysis_flow(request):
        calls.append({"tickers": request.tickers, "account_id": request.account_id})
        return success_response(request.tickers)

    monkeypatch.setattr("app.routes.multi_analysis.run_multi_analysis_flow", fake_run_multi_analysis_flow)

    client = TestClient(make_app())
    response = client.post(
        "/analyze-multi",
        json={"tickers": ["AAPL", "MSFT"], "account_id": "acct-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["execution_summary"]["total_trades_approved"] == 0
    assert [item["analysis"]["ticker"] for item in body["data"]["results"]] == ["AAPL", "MSFT"]
    assert calls == [{"tickers": ["AAPL", "MSFT"], "account_id": "acct-1"}]

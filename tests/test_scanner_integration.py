import datetime

from fastapi.testclient import TestClient

from app.contracts import StandardAgentResponse
from app.main_modular import app
from app.models import (
    AnalysisResult,
    AssetResult,
    ExecutionResult,
    ExecutionSummary,
    MultiOrchestratorResponse,
    ReportDetails,
)

client = TestClient(app)


def scan_response(tickers):
    return StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=datetime.datetime.now(datetime.UTC),
        data=MultiOrchestratorResponse(
            multi_report_id="scan-test-report",
            timestamp=datetime.datetime.now(datetime.UTC),
            execution_summary=ExecutionSummary(
                total_trades_approved=len(tickers),
                total_trades_executed=len(tickers),
                total_trades_failed=0,
            ),
            results=[
                AssetResult(
                    analysis=AnalysisResult(
                        ticker=ticker,
                        final_verdict="buy",
                        status="complete",
                        details=ReportDetails(technical=None, fundamental=None),
                    ),
                    execution=ExecutionResult(status="submitted", details={}),
                )
                for ticker in tickers
            ],
        ),
    )


def test_scan_and_analyze_technical_success(monkeypatch):
    calls = []

    async def fake_run_scan_and_analyze_flow(request):
        calls.append(request.model_dump(mode="json"))
        return scan_response(["AAPL"])

    monkeypatch.setattr("app.routes.scanner.run_scan_and_analyze_flow", fake_run_scan_and_analyze_flow)

    response = client.post("/scan-and-analyze", json={"scan_type": "technical", "max_candidates": 1})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["results"][0]["analysis"]["ticker"] == "AAPL"
    assert calls == [
        {
            "symbols": None,
            "scan_type": "technical",
            "account_id": None,
            "max_candidates": 1,
        }
    ]


def test_scan_and_analyze_no_candidates(monkeypatch):
    async def fake_run_scan_and_analyze_flow(request):
        return scan_response([])

    monkeypatch.setattr("app.routes.scanner.run_scan_and_analyze_flow", fake_run_scan_and_analyze_flow)

    response = client.post("/scan-and-analyze", json={"scan_type": "technical", "max_candidates": 5})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["results"] == []
    assert data["execution_summary"]["total_trades_approved"] == 0


def test_scan_and_analyze_with_pydantic_model_payload_shape(monkeypatch):
    calls = []

    async def fake_run_scan_and_analyze_flow(request):
        calls.append(request.model_dump(mode="json"))
        return scan_response(["TSLA", "GOOG"])

    monkeypatch.setattr("app.routes.scanner.run_scan_and_analyze_flow", fake_run_scan_and_analyze_flow)

    response = client.post("/scan-and-analyze", json={"scan_type": "technical", "max_candidates": 2})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["results"][0]["analysis"]["ticker"] == "TSLA"
    assert data["results"][1]["analysis"]["ticker"] == "GOOG"
    assert calls[0]["max_candidates"] == 2

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


def multi_response(items, approved, executed, failed=0):
    return StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=datetime.datetime.now(datetime.UTC),
        data=MultiOrchestratorResponse(
            multi_report_id="multi-test-report",
            timestamp=datetime.datetime.now(datetime.UTC),
            execution_summary=ExecutionSummary(
                total_trades_approved=approved,
                total_trades_executed=executed,
                total_trades_failed=failed,
            ),
            results=[
                AssetResult(
                    analysis=AnalysisResult(
                        ticker=item["ticker"],
                        final_verdict=item.get("verdict", "buy"),
                        status="complete",
                        details=ReportDetails(technical=None, fundamental=None),
                    ),
                    execution=ExecutionResult(
                        status=item.get("status", "submitted"),
                        reason=item.get("reason"),
                        details=item.get("details"),
                    ),
                )
                for item in items
            ],
        ),
    )


def test_analyze_multi_endpoint_success(monkeypatch):
    calls = []

    async def fake_run_multi_analysis_flow(request):
        calls.append(request.model_dump(mode="json"))
        return multi_response(
            [
                {"ticker": "AAPL"},
                {"ticker": "GOOG", "verdict": "sell"},
                {"ticker": "MSFT"},
            ],
            approved=3,
            executed=3,
        )

    monkeypatch.setattr("app.routes.multi_analysis.run_multi_analysis_flow", fake_run_multi_analysis_flow)

    response = client.post("/analyze-multi", json={"tickers": ["AAPL", "GOOG", "MSFT"]})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["execution_summary"]["total_trades_approved"] == 3
    assert data["execution_summary"]["total_trades_executed"] == 3
    assert [row["analysis"]["ticker"] for row in data["results"]] == ["AAPL", "GOOG", "MSFT"]
    assert calls == [{"tickers": ["AAPL", "GOOG", "MSFT"], "period": "1mo", "account_id": None}]


def test_position_scaling_on_risk_budget(monkeypatch):
    async def fake_run_multi_analysis_flow(request):
        return multi_response(
            [
                {"ticker": "AAPL"},
                {"ticker": "MSFT", "reason": "Position scaled down due to risk budget."},
            ],
            approved=2,
            executed=1,
            failed=1,
        )

    monkeypatch.setattr("app.routes.multi_analysis.run_multi_analysis_flow", fake_run_multi_analysis_flow)

    response = client.post("/analyze-multi", json={"tickers": ["AAPL", "MSFT"]})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["execution_summary"]["total_trades_approved"] == 2
    msft_result = next(row for row in data["results"] if row["analysis"]["ticker"] == "MSFT")
    assert "Position scaled down" in msft_result["execution"]["reason"]


def test_max_exposure_limit(monkeypatch):
    async def fake_run_multi_analysis_flow(request):
        return multi_response(
            [
                {"ticker": "AAPL"},
                {
                    "ticker": "MSFT",
                    "status": "rejected",
                    "reason": "Trade exceeds max total portfolio exposure.",
                },
            ],
            approved=1,
            executed=1,
        )

    monkeypatch.setattr("app.routes.multi_analysis.run_multi_analysis_flow", fake_run_multi_analysis_flow)

    response = client.post("/analyze-multi", json={"tickers": ["AAPL", "MSFT"]})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["execution_summary"]["total_trades_approved"] == 1
    msft_result = next(row for row in data["results"] if row["analysis"]["ticker"] == "MSFT")
    assert "exceeds max total portfolio exposure" in msft_result["execution"]["reason"]

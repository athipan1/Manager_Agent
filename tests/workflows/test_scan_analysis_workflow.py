import datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.contracts import StandardAgentResponse
from app.models import ScanAndAnalyzeRequest
from app.workflows.scan_analysis_workflow import (
    empty_scan_response,
    scanner_candidate_recommendation,
    scanner_candidate_symbol,
    scanner_candidates_from_response_data,
    selected_scan_tickers,
    sort_technical_candidates,
    run_scan_and_analyze_flow,
)


class FakeScannerClient:
    response_data = {"candidates": []}
    calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def scan(self, symbols, correlation_id):
        self.calls.append({"method": "scan", "symbols": symbols})
        return SimpleNamespace(data=self.response_data)

    async def scan_fundamental(self, symbols, correlation_id):
        self.calls.append({"method": "scan_fundamental", "symbols": symbols})
        return SimpleNamespace(data=self.response_data)


def test_scanner_candidates_from_response_data_handles_dict_and_model_dump():
    model_like = SimpleNamespace(model_dump=lambda mode="json": {"candidates": [{"symbol": "MSFT"}]})

    assert scanner_candidates_from_response_data({"candidates": [{"symbol": "AAPL"}]}) == [{"symbol": "AAPL"}]
    assert scanner_candidates_from_response_data(model_like) == [{"symbol": "MSFT"}]
    assert scanner_candidates_from_response_data(None) == []


def test_candidate_accessors_handle_dict_and_object():
    obj = SimpleNamespace(symbol="AAPL", recommendation="STRONG_BUY")

    assert scanner_candidate_symbol({"symbol": "MSFT"}) == "MSFT"
    assert scanner_candidate_symbol(obj) == "AAPL"
    assert scanner_candidate_recommendation({"recommendation": "BUY"}) == "BUY"
    assert scanner_candidate_recommendation(obj) == "STRONG_BUY"


def test_sort_technical_candidates_puts_strong_buy_first():
    candidates = [
        {"symbol": "HOLD", "recommendation": "HOLD"},
        {"symbol": "BUY", "recommendation": "BUY"},
        {"symbol": "STRONG", "recommendation": "STRONG_BUY"},
    ]

    sorted_candidates = sort_technical_candidates(candidates)

    assert [candidate["symbol"] for candidate in sorted_candidates] == ["STRONG", "HOLD", "BUY"]


def test_selected_scan_tickers_caps_and_skips_empty_symbols():
    candidates = [{"symbol": "AAPL"}, {"symbol": None}, {"symbol": "MSFT"}]

    assert selected_scan_tickers(candidates, 3) == ["AAPL", "MSFT"]
    assert selected_scan_tickers(candidates, 1) == ["AAPL"]


def test_empty_scan_response_returns_success_multi_report():
    response = empty_scan_response("cid-1")

    assert response.status == "success"
    assert response.data.multi_report_id == "cid-1"
    assert response.data.execution_summary.total_trades_approved == 0
    assert response.data.results == []


@pytest.mark.asyncio
async def test_run_scan_and_analyze_flow_returns_empty_report_without_candidates(monkeypatch):
    FakeScannerClient.response_data = {"candidates": []}
    FakeScannerClient.calls = []
    monkeypatch.setattr("app.workflows.scan_analysis_workflow.ScannerAgentClient", FakeScannerClient)
    monkeypatch.setattr("app.workflows.scan_analysis_workflow.config_manager.get", lambda key: "acct-1")

    response = await run_scan_and_analyze_flow(ScanAndAnalyzeRequest(symbols=["AAPL"], scan_type="technical"))

    assert response.status == "success"
    assert response.data.results == []
    assert FakeScannerClient.calls == [{"method": "scan", "symbols": ["AAPL"]}]


@pytest.mark.asyncio
async def test_run_scan_and_analyze_flow_delegates_selected_tickers_to_multi_analysis(monkeypatch):
    FakeScannerClient.response_data = {
        "candidates": [
            {"symbol": "MSFT", "recommendation": "BUY"},
            {"symbol": "AAPL", "recommendation": "STRONG_BUY"},
            {"symbol": "TSLA", "recommendation": "BUY"},
        ]
    }
    FakeScannerClient.calls = []
    monkeypatch.setattr("app.workflows.scan_analysis_workflow.ScannerAgentClient", FakeScannerClient)
    monkeypatch.setattr("app.workflows.scan_analysis_workflow.config_manager.get", lambda key: "acct-1")

    calls = []

    async def fake_run_multi_analysis_flow(request):
        calls.append(request)
        return StandardAgentResponse(
            status="success",
            agent_type="manager-agent",
            version="1.0.0",
            timestamp=datetime.datetime.now(datetime.UTC),
            data={"tickers": request.tickers, "account_id": request.account_id},
        )

    monkeypatch.setattr("app.workflows.scan_analysis_workflow.run_multi_analysis_flow", fake_run_multi_analysis_flow)

    response = await run_scan_and_analyze_flow(
        ScanAndAnalyzeRequest(symbols=["AAPL", "MSFT"], scan_type="technical", account_id="acct-2", max_candidates=2)
    )

    assert response.status == "success"
    assert response.data == {"tickers": ["AAPL", "MSFT"], "account_id": "acct-2"}
    assert len(calls) == 1
    assert calls[0].tickers == ["AAPL", "MSFT"]
    assert calls[0].account_id == "acct-2"


@pytest.mark.asyncio
async def test_run_scan_and_analyze_flow_uses_fundamental_scan(monkeypatch):
    FakeScannerClient.response_data = {"candidates": []}
    FakeScannerClient.calls = []
    monkeypatch.setattr("app.workflows.scan_analysis_workflow.ScannerAgentClient", FakeScannerClient)
    monkeypatch.setattr("app.workflows.scan_analysis_workflow.config_manager.get", lambda key: "acct-1")

    await run_scan_and_analyze_flow(ScanAndAnalyzeRequest(symbols=["AAPL"], scan_type="fundamental"))

    assert FakeScannerClient.calls == [{"method": "scan_fundamental", "symbols": ["AAPL"]}]

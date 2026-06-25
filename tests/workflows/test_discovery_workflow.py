from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models import DiscoverAnalyzeTradeRequest, ReportDetails
from app.workflows.discovery_workflow import (
    initial_discovery_execution_result,
    no_scanner_candidates_response,
    no_valid_analysis_response,
    rank_discovery_candidates,
    run_discover_analyze_trade_flow,
    scanner_payload,
    select_unique_scanner_tickers,
)


class FakeScannerClient:
    response = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def discover_best_fundamentals(self, **kwargs):
        return self.response


class FakeDbClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get_account_balance(self, account_id, correlation_id):
        return SimpleNamespace(cash_balance=Decimal("10000"))

    async def get_positions(self, account_id, correlation_id):
        return []

    async def save_signal(self, **kwargs):
        return None


def analysis_result(ticker, verdict="buy"):
    return {
        "ticker": ticker,
        "final_verdict": verdict,
        "status": "complete",
        "details": ReportDetails(technical=None, fundamental=None),
        "raw_data": {},
    }


def test_scanner_payload_normalizes_model_dump_data():
    data = SimpleNamespace(model_dump=lambda: {"candidates": [{"symbol": "AAPL"}]})
    response = SimpleNamespace(data=data)

    assert scanner_payload(response) == {"candidates": [{"symbol": "AAPL"}]}


def test_select_unique_scanner_tickers_dedupes_and_validates(monkeypatch):
    validated = []
    monkeypatch.setattr("app.workflows.discovery_workflow.validate_stock_scope", lambda symbol: validated.append(symbol))

    tickers, mapping = select_unique_scanner_tickers(
        [
            {"symbol": "aapl", "candidate_score": 0.9},
            {"symbol": "AAPL", "candidate_score": 0.8},
            {"symbol": "msft", "candidate_score": 0.7},
            {"candidate_score": 0.5},
        ]
    )

    assert tickers == ["AAPL", "MSFT"]
    assert list(mapping.keys()) == ["AAPL", "MSFT"]
    assert validated == ["AAPL", "MSFT"]


def test_rank_discovery_candidates_orders_by_opportunity_score(monkeypatch):
    def fake_score_deep_analysis(result, scanner_score):
        return {"final_opportunity_score": scanner_score}

    monkeypatch.setattr("app.workflows.discovery_workflow.score_deep_analysis", fake_score_deep_analysis)

    ranked = rank_discovery_candidates(
        valid_results=[analysis_result("AAPL"), analysis_result("MSFT")],
        ticker_to_scanner_candidate={
            "AAPL": {"symbol": "AAPL", "candidate_score": 0.2},
            "MSFT": {"symbol": "MSFT", "candidate_score": 0.9},
        },
    )

    assert [item["symbol"] for item in ranked] == ["MSFT", "AAPL"]


def test_error_response_builders_preserve_legacy_shape():
    scanner_response = no_scanner_candidates_response(
        correlation_id="cid-1",
        scan_response=SimpleNamespace(error="scanner down"),
        scan_payload={"candidates": []},
    )
    analysis_response = no_valid_analysis_response(
        correlation_id="cid-2",
        selected_tickers=["AAPL"],
        analysis_results=[{"error": "agent failed"}],
    )

    assert scanner_response.status == "error"
    assert scanner_response.error["code"] == "NO_SCANNER_CANDIDATES"
    assert scanner_response.data["stage"] == "scanner_discovery"
    assert analysis_response.status == "error"
    assert analysis_response.error["code"] == "NO_VALID_ANALYSIS"
    assert analysis_response.data["stage"] == "deep_analysis"


def test_initial_discovery_execution_result_reflects_execute_flag():
    assert initial_discovery_execution_result(execute=False)["reason"] == "request.execute=false"
    assert initial_discovery_execution_result(execute=True)["reason"] == "No selected positions passed portfolio selection."


@pytest.mark.asyncio
async def test_run_discover_analyze_trade_flow_no_scanner_candidates(monkeypatch):
    FakeScannerClient.response = SimpleNamespace(data={"candidates": []}, error="empty")
    monkeypatch.setattr("app.workflows.discovery_workflow.ScannerAgentClient", FakeScannerClient)
    monkeypatch.setattr("app.workflows.discovery_workflow.config_manager.get", lambda key: "acct-1")

    response = await run_discover_analyze_trade_flow(DiscoverAnalyzeTradeRequest())

    assert response.status == "error"
    assert response.error["code"] == "NO_SCANNER_CANDIDATES"


@pytest.mark.asyncio
async def test_run_discover_analyze_trade_flow_happy_path_without_execution(monkeypatch):
    FakeScannerClient.response = SimpleNamespace(
        data={
            "metadata": {"source": "fake-scanner"},
            "candidates": [
                {"symbol": "AAPL", "candidate_score": 0.95},
                {"symbol": "MSFT", "candidate_score": 0.85},
            ],
        },
        error=None,
    )
    monkeypatch.setattr("app.workflows.discovery_workflow.ScannerAgentClient", FakeScannerClient)
    monkeypatch.setattr("app.workflows.discovery_workflow.DatabaseAgentClient", FakeDbClient)
    monkeypatch.setattr("app.workflows.discovery_workflow.validate_stock_scope", lambda symbol: None)
    monkeypatch.setattr("app.workflows.discovery_workflow.config_manager.get", lambda key: "acct-1")

    async def fake_analyze_single_asset(ticker, correlation_id):
        return analysis_result(ticker)

    async def fake_fetch_context_value(db_client, account_id, correlation_id):
        return Decimal("0")

    async def fake_fetch_session_risk_contexts(db_client, account_id, symbols, correlation_id):
        return {"symbol_contexts": {symbol: {} for symbol in symbols}}

    def fake_build_discover_allocation_report(**kwargs):
        return {
            "allocation_plan": {"policy_name": "test-policy"},
            "bucket_selection": {},
            "selected_positions": [{"symbol": "AAPL"}],
            "position_analysis_payloads": [analysis_result("AAPL")],
            "ranked_candidates": kwargs["ranked"],
            "winner": "AAPL",
        }

    persist_calls = []

    async def fake_persist_signal(*args, **kwargs):
        persist_calls.append(kwargs)

    monkeypatch.setattr("app.workflows.discovery_workflow.analyze_single_asset", fake_analyze_single_asset)
    monkeypatch.setattr("app.workflows.discovery_workflow.fetch_context_value", fake_fetch_context_value)
    monkeypatch.setattr("app.workflows.discovery_workflow.fetch_session_risk_contexts", fake_fetch_session_risk_contexts)
    monkeypatch.setattr("app.workflows.discovery_workflow.build_discover_allocation_report", fake_build_discover_allocation_report)
    monkeypatch.setattr("app.workflows.discovery_workflow.persist_signal", fake_persist_signal)

    response = await run_discover_analyze_trade_flow(DiscoverAnalyzeTradeRequest(execute=False))

    assert response.status == "success"
    assert response.data["flow"] == "discover_analyze_trade"
    assert response.data["scanner_count"] == 2
    assert response.data["deep_analysis_count"] == 2
    assert response.data["execution"]["status"] == "not_attempted"
    assert response.data["execution"]["reason"] == "request.execute=false"
    assert response.data["portfolio_summary"]["policy_name"] == "test-policy"
    assert len(persist_calls) == 2

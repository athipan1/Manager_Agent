from datetime import datetime, timezone

import pytest

from app.contracts import StandardAgentResponse
from app.models import DiscoverAnalyzeTradeRequest
from app.scanner_client import _apply_scanner_data_quality_gate
from app.workflows.discovery_workflow import run_discover_analyze_trade_flow


class FakeScannerClient:
    response = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def discover_best_fundamentals(self, **kwargs):
        return self.response


def _low_quality_scanner_response():
    response = StandardAgentResponse(
        status="success",
        agent_type="scanner",
        version="1.3.0",
        timestamp=datetime.now(timezone.utc),
        correlation_id="quality-workflow-test",
        data={
            "scan_type": "best_fundamentals",
            "count": 1,
            "candidates": [
                {
                    "symbol": "AAPL",
                    "candidate_score": 0.95,
                    "recommendation_hint": "FUNDAMENTAL_TOP_10",
                    "raw_scores": {"evidence_coverage": 0.50},
                    "metadata": {
                        "source": "real_market_fundamental_discovery",
                        "data_bundle": {
                            "schema_version": "scanner-data-bundle.v1",
                            "symbol": "AAPL",
                            "data_quality": {
                                "status": "partial",
                                "coverage_ratio": 0.50,
                                "missing_components": ["financial_statements"],
                            },
                        },
                    },
                }
            ],
            "metadata": {},
            "errors": {},
        },
    )
    return _apply_scanner_data_quality_gate(response)


@pytest.mark.asyncio
async def test_low_quality_scanner_candidate_never_reaches_deep_analysis(monkeypatch):
    monkeypatch.setenv("SCANNER_MIN_DATA_COVERAGE", "0.80")
    FakeScannerClient.response = _low_quality_scanner_response()
    monkeypatch.setattr(
        "app.workflows.discovery_workflow.ScannerAgentClient",
        FakeScannerClient,
    )
    monkeypatch.setattr(
        "app.workflows.discovery_workflow.config_manager.get",
        lambda key: "acct-1",
    )

    async def forbidden_analysis(*args, **kwargs):
        raise AssertionError(
            "Technical/Fundamental analysis must not run for REVIEW candidates"
        )

    monkeypatch.setattr(
        "app.workflows.discovery_workflow.analyze_single_asset",
        forbidden_analysis,
    )

    response = await run_discover_analyze_trade_flow(
        DiscoverAnalyzeTradeRequest(execute=False)
    )

    # Existing outer envelope remains legacy-compatible, while Scanner evidence
    # explicitly records REVIEW and the workflow returns before deep analysis.
    assert response.status == "error"
    assert response.error["code"] == "NO_SCANNER_CANDIDATES"
    scanner_data = response.data["scanner_data"]
    assert scanner_data["candidates"] == []
    assert scanner_data["review_candidates"][0]["symbol"] == "AAPL"
    assert scanner_data["review_candidates"][0]["decision"] == "REVIEW"
    assert (
        scanner_data["review_candidates"][0]["reason_code"]
        == "SCANNER_DATA_COVERAGE_BELOW_THRESHOLD"
    )
    gate = scanner_data["metadata"]["scanner_data_quality_gate"]
    assert gate["decision"] == "REVIEW"
    assert gate["passed_count"] == 0
    assert gate["review_count"] == 1

import pytest

from app.workflows.analysis_workflow import (
    analyze_single_asset,
    clear_deep_analysis_cache,
    process_agent_response,
)


@pytest.fixture(autouse=True)
def _clear_analysis_cache():
    clear_deep_analysis_cache()
    yield
    clear_deep_analysis_cache()


def success_response(data):
    return {"status": "success", "data": data}


def test_process_agent_response_converts_success_response_to_report_detail():
    detail = process_agent_response(
        success_response(
            {
                "action": "buy",
                "confidence_score": 75,
                "reason": "breakout",
            }
        ),
        "technical",
    )

    assert detail.action == "buy"
    assert detail.score == 0.75
    assert detail.reason == "breakout"


def test_process_agent_response_defaults_invalid_action_to_hold():
    detail = process_agent_response(
        success_response({"action": "moon", "confidence_score": 0.5}),
        "fundamental",
    )

    assert detail.action == "hold"
    assert detail.score == 0.5
    assert isinstance(detail.reason, str)


def test_process_agent_response_returns_none_on_error_or_missing_data():
    assert (
        process_agent_response(
            {"status": "error", "data": {"action": "buy"}},
            "technical",
        )
        is None
    )
    assert (
        process_agent_response(
            {"status": "success", "data": []},
            "technical",
        )
        is None
    )


def _patch_successful_analysis(monkeypatch, calls):
    async def fake_call_agents(ticker, correlation_id):
        calls.append((ticker, correlation_id))
        return (
            success_response(
                {
                    "action": "buy",
                    "confidence_score": 80,
                    "reason": "trend",
                }
            ),
            success_response(
                {
                    "action": "buy",
                    "confidence_score": 60,
                    "reason": "quality",
                }
            ),
        )

    monkeypatch.setattr(
        "app.workflows.analysis_workflow.call_agents",
        fake_call_agents,
    )
    monkeypatch.setattr(
        "app.workflows.analysis_workflow.validate_stock_scope",
        lambda ticker: None,
    )
    monkeypatch.setattr(
        "app.workflows.analysis_workflow.get_weighted_verdict",
        lambda tech_action, tech_score, fund_action, fund_score, asset_symbol: (
            "buy"
        ),
    )


@pytest.mark.asyncio
async def test_analyze_single_asset_returns_complete_report(monkeypatch):
    calls = []
    _patch_successful_analysis(monkeypatch, calls)

    result = await analyze_single_asset("AAPL", "cid")

    assert result["ticker"] == "AAPL"
    assert result["final_verdict"] == "buy"
    assert result["status"] == "complete"
    assert result["details"].technical.action == "buy"
    assert result["details"].fundamental.action == "buy"
    assert result["raw_data"]["technical"]["data"]["reason"] == "trend"
    assert result["analysis_cache"]["hit"] is False
    assert result["analysis_cache"]["stored"] is True
    assert calls == [("AAPL", "cid")]


@pytest.mark.asyncio
async def test_analyze_single_asset_reuses_one_shot_result(monkeypatch):
    calls = []
    _patch_successful_analysis(monkeypatch, calls)

    first = await analyze_single_asset("aapl", "step-19")
    second = await analyze_single_asset("AAPL", "step-21")

    assert first["analysis_cache"]["hit"] is False
    assert second["analysis_cache"]["hit"] is True
    assert second["analysis_cache"]["one_shot"] is True
    assert second["analysis_cache"]["source_correlation_id"] == "step-19"
    assert second["analysis_cache"]["request_correlation_id"] == "step-21"
    assert second["analysis_cache"]["age_seconds"] >= 0
    assert calls == [("AAPL", "step-19")]

    third = await analyze_single_asset("AAPL", "later-request")
    assert third["analysis_cache"]["hit"] is False
    assert calls == [
        ("AAPL", "step-19"),
        ("AAPL", "later-request"),
    ]


@pytest.mark.asyncio
async def test_analyze_single_asset_returns_partial_when_one_agent_fails(
    monkeypatch,
):
    calls = []

    async def fake_call_agents(ticker, correlation_id):
        calls.append((ticker, correlation_id))
        return (
            {"status": "error", "data": {}},
            success_response(
                {
                    "action": "buy",
                    "confidence_score": 60,
                    "reason": "quality",
                }
            ),
        )

    monkeypatch.setattr(
        "app.workflows.analysis_workflow.call_agents",
        fake_call_agents,
    )
    monkeypatch.setattr(
        "app.workflows.analysis_workflow.validate_stock_scope",
        lambda ticker: None,
    )
    monkeypatch.setattr(
        "app.workflows.analysis_workflow.get_weighted_verdict",
        lambda tech_action, tech_score, fund_action, fund_score, asset_symbol: (
            "hold"
        ),
    )

    result = await analyze_single_asset("AAPL", "cid")
    reused = await analyze_single_asset("AAPL", "cid-2")

    assert result["status"] == "partial"
    assert result["details"].technical is None
    assert result["details"].fundamental.action == "buy"
    assert result["final_verdict"] == "hold"
    assert reused["analysis_cache"]["hit"] is True
    assert calls == [("AAPL", "cid")]


@pytest.mark.asyncio
async def test_analyze_single_asset_does_not_cache_total_failure(monkeypatch):
    calls = []

    async def fake_call_agents(ticker, correlation_id):
        calls.append((ticker, correlation_id))
        return (
            {"status": "error", "data": {}},
            {"status": "error", "data": {}},
        )

    monkeypatch.setattr(
        "app.workflows.analysis_workflow.call_agents",
        fake_call_agents,
    )
    monkeypatch.setattr(
        "app.workflows.analysis_workflow.validate_stock_scope",
        lambda ticker: None,
    )

    first = await analyze_single_asset("AAPL", "cid-1")
    second = await analyze_single_asset("AAPL", "cid-2")

    assert first["ticker"] == "AAPL"
    assert first["error"] == "All agents failed"
    assert first["analysis_cache"]["stored"] is False
    assert second["analysis_cache"]["hit"] is False
    assert len(calls) == 2
    assert "technical" in first["raw_data"]
    assert "fundamental" in first["raw_data"]

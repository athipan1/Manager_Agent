import pytest

from app.workflows.analysis_workflow import analyze_single_asset, process_agent_response


def success_response(data):
    return {"status": "success", "data": data}


def test_process_agent_response_converts_success_response_to_report_detail():
    detail = process_agent_response(
        success_response({"action": "buy", "confidence_score": 75, "reason": "breakout"}),
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
    assert process_agent_response({"status": "error", "data": {"action": "buy"}}, "technical") is None
    assert process_agent_response({"status": "success", "data": []}, "technical") is None


@pytest.mark.asyncio
async def test_analyze_single_asset_returns_complete_report(monkeypatch):
    async def fake_call_agents(ticker, correlation_id):
        return (
            success_response({"action": "buy", "confidence_score": 80, "reason": "trend"}),
            success_response({"action": "buy", "confidence_score": 60, "reason": "quality"}),
        )

    monkeypatch.setattr("app.workflows.analysis_workflow.call_agents", fake_call_agents)
    monkeypatch.setattr("app.workflows.analysis_workflow.validate_stock_scope", lambda ticker: None)
    monkeypatch.setattr(
        "app.workflows.analysis_workflow.get_weighted_verdict",
        lambda tech_action, tech_score, fund_action, fund_score, asset_symbol: "buy",
    )

    result = await analyze_single_asset("AAPL", "cid")

    assert result["ticker"] == "AAPL"
    assert result["final_verdict"] == "buy"
    assert result["status"] == "complete"
    assert result["details"].technical.action == "buy"
    assert result["details"].fundamental.action == "buy"
    assert result["raw_data"]["technical"]["data"]["reason"] == "trend"


@pytest.mark.asyncio
async def test_analyze_single_asset_returns_partial_when_one_agent_fails(monkeypatch):
    async def fake_call_agents(ticker, correlation_id):
        return (
            {"status": "error", "data": {}},
            success_response({"action": "buy", "confidence_score": 60, "reason": "quality"}),
        )

    monkeypatch.setattr("app.workflows.analysis_workflow.call_agents", fake_call_agents)
    monkeypatch.setattr("app.workflows.analysis_workflow.validate_stock_scope", lambda ticker: None)
    monkeypatch.setattr(
        "app.workflows.analysis_workflow.get_weighted_verdict",
        lambda tech_action, tech_score, fund_action, fund_score, asset_symbol: "hold",
    )

    result = await analyze_single_asset("AAPL", "cid")

    assert result["status"] == "partial"
    assert result["details"].technical is None
    assert result["details"].fundamental.action == "buy"
    assert result["final_verdict"] == "hold"


@pytest.mark.asyncio
async def test_analyze_single_asset_returns_error_when_all_agents_fail(monkeypatch):
    async def fake_call_agents(ticker, correlation_id):
        return (
            {"status": "error", "data": {}},
            {"status": "error", "data": {}},
        )

    monkeypatch.setattr("app.workflows.analysis_workflow.call_agents", fake_call_agents)
    monkeypatch.setattr("app.workflows.analysis_workflow.validate_stock_scope", lambda ticker: None)

    result = await analyze_single_asset("AAPL", "cid")

    assert result["ticker"] == "AAPL"
    assert result["error"] == "All agents failed"
    assert "technical" in result["raw_data"]
    assert "fundamental" in result["raw_data"]

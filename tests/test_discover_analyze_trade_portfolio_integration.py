import datetime

from fastapi.testclient import TestClient

from app.contracts import StandardAgentResponse
from app.main_modular import app

client = TestClient(app)


def portfolio_discovery_response():
    selected_positions = [
        {"symbol": "KO", "strategy_bucket": "core_dividend"},
        {"symbol": "ACGL", "strategy_bucket": "value_rebound"},
        {"symbol": "MSFT", "strategy_bucket": "news_momentum"},
    ]
    risk_approvals = [
        {"symbol": position["symbol"], "approved": True, "risk_approval_id": f"risk-{position['symbol']}"}
        for position in selected_positions
    ]
    return StandardAgentResponse(
        status="success",
        agent_type="manager-agent",
        version="1.0.0",
        timestamp=datetime.datetime.now(datetime.UTC),
        data={
            "report_id": "discover-portfolio-report",
            "flow": "discover_analyze_trade",
            "mode": "portfolio_allocation",
            "allocation_plan": {
                "policy_name": "core_satellite_50_30_20",
                "buckets": {
                    "core_dividend": {"target_weight": 0.5},
                    "value_rebound": {"target_weight": 0.3},
                    "news_momentum": {"target_weight": 0.2},
                },
            },
            "selected_positions": selected_positions,
            "risk_approvals": risk_approvals,
            "execution_candidates": risk_approvals,
            "execution": {
                "status": "submitted",
                "created": [
                    {"symbol": approval["symbol"], "risk_approval_id": approval["risk_approval_id"]}
                    for approval in risk_approvals
                ],
                "failed": [],
            },
            "portfolio_summary": {
                "selected_positions": 3,
                "approved_positions": 3,
            },
            "legacy": {"winner": {"symbol": "KO"}},
        },
    )


def test_discover_analyze_trade_returns_portfolio_contract(monkeypatch):
    calls = []

    async def fake_run_discover_analyze_trade_flow(request):
        calls.append(request.model_dump(mode="json"))
        return portfolio_discovery_response()

    monkeypatch.setattr(
        "app.routes.discovery.run_discover_analyze_trade_flow",
        fake_run_discover_analyze_trade_flow,
    )

    response = client.post(
        "/discover-analyze-trade",
        json={
            "account_id": "1",
            "max_universe": 3,
            "top_n": 3,
            "exchange": "NASDAQ",
            "max_workers": 1,
            "min_final_score": 0.55,
            "execute": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    data = body["data"]

    assert data["mode"] == "portfolio_allocation"
    assert data["allocation_plan"]["policy_name"] == "core_satellite_50_30_20"
    assert data["allocation_plan"]["buckets"]["core_dividend"]["target_weight"] == 0.5
    assert data["allocation_plan"]["buckets"]["value_rebound"]["target_weight"] == 0.3
    assert data["allocation_plan"]["buckets"]["news_momentum"]["target_weight"] == 0.2

    assert [position["symbol"] for position in data["selected_positions"]] == ["KO", "ACGL", "MSFT"]
    assert {position["strategy_bucket"] for position in data["selected_positions"]} == {
        "core_dividend",
        "value_rebound",
        "news_momentum",
    }

    assert len(data["risk_approvals"]) == 3
    assert len(data["execution_candidates"]) == 3
    assert data["execution"]["status"] == "submitted"
    assert len(data["execution"]["created"]) == 3
    assert data["portfolio_summary"]["selected_positions"] == 3
    assert data["portfolio_summary"]["approved_positions"] == 3

    assert "winner" not in data
    assert "trade_decision" not in data
    assert "legacy" in data
    assert calls == [
        {
            "account_id": "1",
            "max_universe": 3,
            "top_n": 3,
            "exchange": "NASDAQ",
            "max_workers": 1,
            "min_final_score": 0.55,
            "execute": True,
        }
    ]

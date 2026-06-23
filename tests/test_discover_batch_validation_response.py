import pytest

from app.stock_preflight import _attach_discover_allocation_response

pytestmark = pytest.mark.asyncio


class ResponseObj:
    def __init__(self, data):
        self.data = data


async def test_discover_response_marks_batch_validation_not_attempted_without_risk_decisions():
    response = ResponseObj({
        "flow": "discover_analyze_trade",
        "report_id": "corr-1",
        "ranked_candidates": [
            {
                "symbol": "KO",
                "final_verdict": "buy",
                "analysis_status": "complete",
                "score_breakdown": {"final_opportunity_score": 0.8},
            }
        ],
    })

    result = await _attach_discover_allocation_response(response)

    assert result.data["allocation_plan"]
    assert result.data["bucket_selection"]
    assert result.data["batch_validation_result"]["status"] == "not_attempted"
    assert result.data["batch_validation_result"]["reason"] == "bucket_risk_decisions missing"
    assert result.data["batch_execution_result"]["status"] == "not_attempted"


async def test_discover_response_calls_batch_validation_when_risk_decisions_exist(monkeypatch):
    async def fake_validate_bucket_batch(**kwargs):
        return {"approved": True, "requests": [], "execution_validation": {"summary": {"order_count": 1}}}

    monkeypatch.setattr("app.batch_validation_bridge.validate_bucket_batch", fake_validate_bucket_batch)

    response = ResponseObj({
        "flow": "discover_analyze_trade",
        "report_id": "corr-1",
        "account_id": 1,
        "ranked_candidates": [
            {
                "symbol": "KO",
                "final_verdict": "buy",
                "analysis_status": "complete",
                "score_breakdown": {"final_opportunity_score": 0.8},
            }
        ],
        "bucket_risk_decisions": {
            "core_dividend": [
                {"approved": True, "symbol": "KO", "action": "buy", "position_size": 1, "risk_approval_id": "risk-ko", "strategy_bucket": "core_dividend"}
            ]
        },
    })

    result = await _attach_discover_allocation_response(response)

    assert result.data["batch_validation_result"]["approved"] is True
    assert result.data["batch_validation_result"]["execution_validation"]["summary"]["order_count"] == 1
    assert result.data["batch_execution_result"]["status"] == "not_attempted"
    assert result.data["batch_execution_result"]["reason"] == "batch execution disabled"


async def test_discover_response_attempts_batch_execution_only_when_enabled(monkeypatch):
    async def fake_validate_bucket_batch(**kwargs):
        return {
            "approved": True,
            "requests": [{
                "client_order_id": "cid-1",
                "account_id": "1",
                "symbol": "KO",
                "side": "buy",
                "order_type": "market",
                "quantity": 1,
                "final_quantity": 1,
                "strategy_bucket": "core_dividend",
                "risk_approval_id": "risk-ko",
                "guard_plan": {"source": "test"},
            }],
            "execution_validation": {"summary": {"order_count": 1}},
        }

    async def fake_execute_order_batch(self, requests, correlation_id):
        return type("Response", (), {"data": {"approved": True, "created": [{"symbol": "KO"}], "failed": []}})()

    monkeypatch.setattr("app.batch_validation_bridge.validate_bucket_batch", fake_validate_bucket_batch)
    monkeypatch.setattr("app.batch_execution_settings.ENABLE_BATCH_EXECUTION", True)
    monkeypatch.setattr("app.config.MANUAL_APPROVAL_REQUIRED", False)
    monkeypatch.setattr("app.execution_client.ExecutionAgentClient.execute_order_batch", fake_execute_order_batch)

    response = ResponseObj({
        "flow": "discover_analyze_trade",
        "report_id": "corr-1",
        "account_id": 1,
        "ranked_candidates": [
            {
                "symbol": "KO",
                "final_verdict": "buy",
                "analysis_status": "complete",
                "score_breakdown": {"final_opportunity_score": 0.8},
            }
        ],
        "bucket_risk_decisions": {
            "core_dividend": [
                {"approved": True, "symbol": "KO", "action": "buy", "position_size": 1, "risk_approval_id": "risk-ko", "strategy_bucket": "core_dividend"}
            ]
        },
    })

    result = await _attach_discover_allocation_response(response)

    assert result.data["batch_execution_result"]["status"] == "attempted"
    assert result.data["batch_execution_result"]["approved"] is True
    assert result.data["batch_execution_result"]["execution"]["created"][0]["symbol"] == "KO"

from app.batch_validation_bridge import build_batch_validation_requests, validate_bucket_batch


class FakeExecutionClient:
    def __init__(self):
        self.calls = []

    async def validate_order_batch(self, requests, correlation_id):
        self.calls.append((requests, correlation_id))
        return type("Response", (), {"data": {"approved": True, "summary": {"order_count": len(requests)}}})()


def test_build_batch_validation_requests_keeps_bucket_metadata():
    decisions = {
        "core_dividend": [
            {"approved": True, "symbol": "KO", "action": "buy", "position_size": 1, "risk_approval_id": "risk-ko", "strategy_bucket": "core_dividend"}
        ],
        "value_rebound": [
            {"approved": True, "symbol": "ACGL", "action": "buy", "position_size": 2, "risk_approval_id": "risk-acgl", "strategy_bucket": "value_rebound"}
        ],
        "news_momentum": [
            {"approved": False, "symbol": "NEWS", "position_size": 1, "risk_approval_id": "risk-news"}
        ],
    }

    requests = build_batch_validation_requests(decisions, account_id=1)

    assert len(requests) == 2
    assert requests[0].symbol == "KO"
    assert requests[0].strategy_bucket == "core_dividend"
    assert requests[1].symbol == "ACGL"
    assert requests[1].strategy_bucket == "value_rebound"


async def test_validate_bucket_batch_calls_execution_validate():
    client = FakeExecutionClient()
    decisions = {
        "core_dividend": [
            {"approved": True, "symbol": "KO", "action": "buy", "position_size": 1, "risk_approval_id": "risk-ko", "strategy_bucket": "core_dividend"}
        ]
    }

    result = await validate_bucket_batch(execution_client=client, bucket_risk_decisions=decisions, account_id=1, correlation_id="corr-1")

    assert result["approved"] is True
    assert result["execution_validation"]["summary"]["order_count"] == 1
    assert len(client.calls) == 1
    assert client.calls[0][1] == "corr-1"


async def test_validate_bucket_batch_handles_empty_requests():
    client = FakeExecutionClient()

    result = await validate_bucket_batch(execution_client=client, bucket_risk_decisions={}, account_id=1, correlation_id="corr-1")

    assert result["approved"] is False
    assert result["reason"] == "no_valid_requests"
    assert client.calls == []

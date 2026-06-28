from types import SimpleNamespace

import pytest

from app.services.performance_policy_review_service import run_performance_policy_review


class ContractDbClient:
    def __init__(self):
        self.posts = []
        self.saved_signals = []

    async def _post(self, endpoint, correlation_id, json_data=None):
        self.posts.append((endpoint, correlation_id, json_data))
        assert endpoint == "/policy-reviews"
        assert json_data["account_id"] == "1"
        assert json_data["symbol"] == "AAPL"
        assert json_data["correlation_id"] == "corr-contract-1"
        assert json_data["status"] == "review_required"
        assert json_data["advisory_only"] is True
        assert json_data["auto_apply"] is False
        assert json_data["performance_summary"]["closed_plan_count"] == 12
        assert json_data["learning_result"]["learning_state"] == "success"
        assert json_data["curated_policy"]["curation_state"] == "review_required"
        assert json_data["metadata"]["flow"] == "performance_policy_review"
        return {
            "status": "success",
            "data": {
                **json_data,
                "created_at": "2026-06-28T00:00:00+00:00",
                "updated_at": "2026-06-28T00:00:00+00:00",
            },
        }

    def validate_standard_response(self, response):
        assert response["status"] == "success"
        return SimpleNamespace(data=response.get("data"))

    async def save_signal(self, **kwargs):
        self.saved_signals.append(kwargs)


class ContractAgentClient:
    calls = []

    def __init__(self, base_url, timeout=None, **kwargs):
        self.base_url = base_url
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def _get(self, endpoint, correlation_id, **kwargs):
        ContractAgentClient.calls.append(("GET", self.base_url, endpoint, correlation_id, kwargs))
        assert endpoint == "/performance/trade-plans/database-summary"
        params = kwargs["params"]
        assert params["account_id"] == "1"
        assert params["symbol"] == "AAPL"
        assert params["initial_equity"] == 10_000
        assert params["period"] == "30d"
        assert params["include_fills"] is True
        return {
            "status": "success",
            "data": {
                "period": "30d",
                "trade_plan_count": 16,
                "closed_plan_count": 12,
                "open_plan_count": 4,
                "win_rate": 0.58,
                "net_pnl": 320.0,
                "expectancy": 26.67,
                "profit_factor": 1.42,
                "by_strategy_bucket": {
                    "value_rebound": {
                        "trade_plan_count": 8,
                        "closed_plan_count": 8,
                        "win_rate": 0.62,
                        "net_pnl": 240.0,
                        "expectancy": 30.0,
                        "profit_factor": 1.5,
                    }
                },
                "by_symbol": {
                    "AAPL": {
                        "trade_plan_count": 12,
                        "closed_plan_count": 12,
                        "win_rate": 0.58,
                        "net_pnl": 320.0,
                        "expectancy": 26.67,
                        "profit_factor": 1.42,
                    }
                },
            },
        }

    async def _post(self, endpoint, correlation_id, json_data=None):
        ContractAgentClient.calls.append(("POST", self.base_url, endpoint, correlation_id, json_data))
        if endpoint == "/learn/performance":
            assert json_data["account_id"] == "1"
            assert json_data["learning_mode"] == "performance_summary_review"
            assert json_data["performance_summary"]["closed_plan_count"] == 12
            assert json_data["performance_summary"]["by_strategy_bucket"]["value_rebound"]["net_pnl"] == 240.0
            assert json_data["current_policy"]["risk"]["risk_per_trade"] == 0.01
            return {
                "status": "success",
                "data": {
                    "learning_state": "success",
                    "learning_mode": "performance_summary_review",
                    "confidence_score": 0.82,
                    "reviewed_closed_plans": 12,
                    "performance_score": 0.74,
                    "policy_deltas": {
                        "strategy_bucket_weights": {"value_rebound": 0.05},
                        "asset_biases": {"AAPL": 0.03},
                        "risk": {},
                        "guardrails": {"requires_human_review": True, "auto_apply": False},
                    },
                    "reasoning": ["profitable bucket observed"],
                },
            }
        if endpoint == "/curate/performance-policy":
            assert json_data["account_id"] == "1"
            assert json_data["learning_result"]["policy_deltas"]["strategy_bucket_weights"]["value_rebound"] == 0.05
            assert json_data["current_policy"]["risk"]["risk_per_trade"] == 0.01
            return {
                "status": "success",
                "data": {
                    "curation_state": "review_required",
                    "action_count": 2,
                    "actions": [
                        {
                            "target_type": "strategy_bucket",
                            "target": "value_rebound",
                            "action": "increase_weight",
                            "delta": 0.05,
                            "auto_apply": False,
                            "priority": "medium",
                            "reason": "Learning_Agent recommended increase_weight.",
                        },
                        {
                            "target_type": "guardrail",
                            "target": "human_review",
                            "action": "require_human_review",
                            "auto_apply": False,
                            "priority": "high",
                            "reason": "Human review is required.",
                        },
                    ],
                    "reasoning": ["Human review required"],
                    "metadata": {"confidence_score": 0.82},
                },
            }
        raise AssertionError(f"unexpected endpoint {endpoint}")

    def validate_standard_response(self, response):
        assert response["status"] == "success"
        return SimpleNamespace(data=response.get("data"))


@pytest.mark.asyncio
async def test_performance_learning_curator_database_policy_review_contract(monkeypatch):
    ContractAgentClient.calls = []
    monkeypatch.setattr("app.services.performance_policy_review_service.config.POLICY_REVIEW_FLOW_ENABLED", True)
    monkeypatch.setattr("app.services.performance_policy_review_service.config.PERFORMANCE_AGENT_URL", "http://performance-agent")
    monkeypatch.setattr("app.services.performance_policy_review_service.config.AUTO_LEARNING_AGENT_URL", "http://learning-agent", raising=False)
    monkeypatch.setattr("app.services.performance_policy_review_service.config.CURATOR_AGENT_URL", "http://curator-agent")
    monkeypatch.setattr("app.services.performance_policy_review_service.config_manager.get", lambda key, default=None: {
        "AGENT_WEIGHTS": {"technical": 0.5, "fundamental": 0.5},
        "RISK_PER_TRADE": 0.01,
        "MAX_POSITION_PERCENTAGE": 0.10,
        "STOP_LOSS_PERCENTAGE": 0.03,
        "ASSET_BIASES": {},
        "PREFERRED_REGIME": "neutral",
    }.get(key, default))
    monkeypatch.setattr("app.services.performance_policy_review_service.ResilientAgentClient", ContractAgentClient)

    db_client = ContractDbClient()
    result = await run_performance_policy_review(
        db_client=db_client,
        account_id="1",
        symbol="AAPL",
        initial_equity=10_000,
        correlation_id="corr-contract-1",
    )

    assert result["status"] == "success"
    assert result["advisory_only"] is True
    assert result["auto_apply"] is False
    assert result["performance_summary"]["closed_plan_count"] == 12
    assert result["learning_result"]["policy_deltas"]["strategy_bucket_weights"]["value_rebound"] == 0.05
    assert result["curated_policy"]["curation_state"] == "review_required"
    assert result["policy_review_audit_id"].startswith("policy-review-")
    assert result["policy_review_audit"]["status"] == "review_required"
    assert db_client.saved_signals == []
    assert [call[2] for call in ContractAgentClient.calls] == [
        "/performance/trade-plans/database-summary",
        "/learn/performance",
        "/curate/performance-policy",
    ]
    assert db_client.posts[0][0] == "/policy-reviews"

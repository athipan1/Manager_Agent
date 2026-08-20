from fastapi.testclient import TestClient

from app.main_modular import app
from app.services.shadow_observation_mapper import shadow_plan_to_observation
from app.services.shadow_trading_service import ShadowPlanRequest, build_shadow_trade_plan


def _candidate():
    return {
        "symbol": "NVDA",
        "confidence_score": 0.66,
        "metadata": {
            "details": {
                "data_bundle": {
                    "opportunity_profile": {
                        "schema_version": "scanner-opportunity-profile.v1",
                        "status": "review",
                        "opportunity_score": 0.62,
                        "preferred_strategy_hint": "trend_following",
                        "strategy_affinity": {"trend_following": 0.71},
                        "execution_context": {
                            "current_price": 180.0,
                            "bid": 179.98,
                            "ask": 180.02,
                            "spread_bps": 2.22,
                            "estimated_dollar_volume": 250000000.0,
                            "atr_pct": 0.03,
                        },
                    }
                }
            },
            "market_regime": {"regime": "BULL"},
        },
    }


class FakeShadowDatabaseAgentClient:
    recorded = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def create_shadow_observation(self, payload, correlation_id):
        self.__class__.recorded.append((payload, correlation_id))
        return {
            **payload,
            "event_id": "shadow-event-1",
            "created_at": "2026-08-20T15:00:00+00:00",
        }


def test_shadow_mapper_keeps_database_event_broker_isolated():
    plan = build_shadow_trade_plan(
        ShadowPlanRequest(
            account_id="paper-account",
            candidate=_candidate(),
            correlation_id="corr-shadow-map",
        )
    )

    observation = shadow_plan_to_observation(plan)

    assert observation["execution_mode"] == "shadow"
    assert observation["broker_order_authorized"] is False
    assert observation["metadata"]["lane"] == "research"
    assert observation["metadata"]["risk_approval_allowed"] is False
    assert observation["metadata"]["execution_agent_allowed"] is False


def test_record_endpoint_writes_database_only(monkeypatch):
    from app.routes import shadow_trading

    FakeShadowDatabaseAgentClient.recorded = []
    monkeypatch.setattr(
        shadow_trading,
        "ShadowDatabaseAgentClient",
        FakeShadowDatabaseAgentClient,
    )
    client = TestClient(app)
    response = client.post(
        "/shadow-trading/record",
        json={
            "account_id": "paper-account",
            "candidate": _candidate(),
            "correlation_id": "corr-shadow-record",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["execution_mode"] == "shadow"
    assert body["broker_order_authorized"] is False
    assert body["risk_approval_allowed"] is False
    assert body["execution_agent_allowed"] is False
    assert body["observation"]["event_id"] == "shadow-event-1"
    assert len(FakeShadowDatabaseAgentClient.recorded) == 1
    recorded, correlation_id = FakeShadowDatabaseAgentClient.recorded[0]
    assert correlation_id == "corr-shadow-record"
    assert recorded["event_type"] == "signal_decision"
    assert recorded["broker_order_authorized"] is False


def test_record_batch_keeps_research_and_rejected_evidence_separate(monkeypatch):
    from app.routes import shadow_trading

    FakeShadowDatabaseAgentClient.recorded = []
    monkeypatch.setattr(
        shadow_trading,
        "ShadowDatabaseAgentClient",
        FakeShadowDatabaseAgentClient,
    )
    bad = _candidate()
    bad["metadata"]["details"]["data_bundle"]["opportunity_profile"]["opportunity_score"] = 0.20
    client = TestClient(app)
    response = client.post(
        "/shadow-trading/record/batch",
        json={
            "account_id": "paper-account",
            "correlation_id": "corr-shadow-batch",
            "candidates": [_candidate(), bad],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["planned_count"] == 1
    assert body["recorded_count"] == 1
    assert body["rejected_count"] == 1
    assert body["persistence_error_count"] == 0
    assert body["broker_order_authorized"] is False

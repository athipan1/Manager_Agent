from fastapi.testclient import TestClient

from app.main_modular import app
from app.services.shadow_trading_service import (
    ShadowPlanRequest,
    build_shadow_trade_plan,
)


def _candidate(status="review", score=0.62):
    return {
        "symbol": "NVDA",
        "confidence_score": 0.66,
        "metadata": {
            "details": {
                "data_bundle": {
                    "opportunity_profile": {
                        "schema_version": "scanner-opportunity-profile.v1",
                        "status": status,
                        "opportunity_score": score,
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


def test_shadow_plan_is_deterministic_and_broker_isolated():
    request = ShadowPlanRequest(
        account_id="paper-account",
        candidate=_candidate(),
        correlation_id="corr-shadow-1",
        strategy_version="v7",
    )

    first = build_shadow_trade_plan(request)
    replay = build_shadow_trade_plan(request)

    assert first.shadow_trade_id == replay.shadow_trade_id
    assert first.signal_id == replay.signal_id
    assert first.execution_mode == "shadow"
    assert first.lane == "research"
    assert first.broker_order_authorized is False
    assert first.risk_approval_allowed is False
    assert first.execution_agent_allowed is False
    assert first.simulated_fill_price == 180.02
    assert first.market_regime == "BULL"


def test_shadow_plan_rejects_non_research_candidate():
    request = ShadowPlanRequest(
        account_id=1,
        candidate=_candidate(status="avoid", score=0.30),
        correlation_id="corr-shadow-2",
    )

    try:
        build_shadow_trade_plan(request)
    except ValueError as exc:
        assert "not eligible" in str(exc)
    else:
        raise AssertionError("ineligible candidate was accepted into shadow lane")


def test_shadow_http_batch_never_grants_execution_authority():
    client = TestClient(app)
    response = client.post(
        "/shadow-trading/plan/batch",
        json={
            "account_id": "paper-account",
            "correlation_id": "corr-shadow-http",
            "candidates": [_candidate()],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["planned_count"] == 1
    assert body["execution_mode"] == "shadow"
    assert body["broker_order_authorized"] is False
    assert body["risk_approval_allowed"] is False
    assert body["execution_agent_allowed"] is False
    assert body["plans"][0]["execution_agent_allowed"] is False

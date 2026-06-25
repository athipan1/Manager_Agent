import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routes.trade_replay import router


def make_app():
    app = FastAPI()
    app.include_router(router)
    return app


def test_trade_replay_returns_dry_run_audit_payload(monkeypatch):
    monkeypatch.setattr(
        "app.routes.trade_replay.utc_now",
        lambda: datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )

    client = TestClient(make_app())
    response = client.post(
        "/trade-replay",
        json={
            "symbol": "AAPL",
            "risk_context": {"open_orders_exposure": "123.45"},
            "analysis": {"ticker": "AAPL", "final_verdict": "buy"},
            "trade_decision": {
                "symbol": "AAPL",
                "risk_approval_id": "risk-123",
                "session_risk_context": {"trades_today": 1},
            },
            "execution": {"status": "submitted"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data"]["flow"] == "trade_replay"
    assert body["data"]["symbol"] == "AAPL"
    assert body["data"]["dry_run"] is True
    assert body["data"]["risk_context"]["open_orders_exposure"] == 123.45
    assert body["data"]["risk_approval_id"] == "risk-123"
    assert body["metadata"]["dry_run"] is True
    assert body["metadata"]["risk_context_loaded"] is True


def test_trade_replay_handles_missing_optional_payload_sections(monkeypatch):
    monkeypatch.setattr(
        "app.routes.trade_replay.utc_now",
        lambda: datetime.datetime(2026, 1, 1, tzinfo=datetime.UTC),
    )

    client = TestClient(make_app())
    response = client.post("/trade-replay", json={"symbol": "MSFT"})

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["symbol"] == "MSFT"
    assert body["data"]["analysis"] is None
    assert body["data"]["trade_decision"] is None
    assert body["data"]["execution"] is None
    assert body["data"]["risk_context"]["open_orders_exposure"] == 0.0

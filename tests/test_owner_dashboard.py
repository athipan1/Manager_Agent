from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app.main import app


OWNER_PAYLOAD = {
    "generated_at": "2026-08-12T07:00:00+00:00",
    "data_source": "broker_fallback",
    "balance": {
        "cash": "12500.25",
        "equity": "15120.75",
        "buying_power": "25000.50",
        "status": "ACTIVE",
    },
    "positions": [
        {
            "symbol": "AAPL",
            "qty": "2",
            "avg_entry_price": "200.00",
            "current_price": "205.00",
            "market_value": "410.00",
            "unrealized_pl": "10.00",
        }
    ],
    "open_orders": [],
    "curator_signals": [],
    "problems": [],
    "summary": {"problem_count": 0},
}


def test_owner_snapshot_requires_operator_token(monkeypatch):
    monkeypatch.setenv("WEB_CONTROL_OPERATOR_TOKEN", "owner-secret")
    client = TestClient(app)

    response = client.get("/web-control/owner-snapshot")

    assert response.status_code == 401


def test_owner_snapshot_returns_full_values_without_cache(monkeypatch):
    monkeypatch.setenv("WEB_CONTROL_OPERATOR_TOKEN", "owner-secret")
    client = TestClient(app)

    with patch(
        "app.routes.owner_dashboard._dashboard_payload",
        new=AsyncMock(return_value=OWNER_PAYLOAD),
    ):
        response = client.get(
            "/web-control/owner-snapshot?account_id=1",
            headers={"X-Operator-Token": "owner-secret"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["schemaVersion"] == "dashboard-snapshot.v1"
    assert body["account"]["cash"] == 12500.25
    assert body["account"]["equity"] == 15120.75
    assert body["account"]["buyingPower"] == 25000.5
    assert body["positions"][0]["marketValue"] == 410.0
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert response.headers["x-privacy-mode"] == "owner-authenticated"
    assert response.headers["x-request-id"]


def test_owner_snapshot_hides_upstream_failure_details(monkeypatch):
    monkeypatch.setenv("WEB_CONTROL_OPERATOR_TOKEN", "owner-secret")
    client = TestClient(app)

    with patch(
        "app.routes.owner_dashboard._dashboard_payload",
        new=AsyncMock(side_effect=RuntimeError("https://secret.internal?api_key=should-not-leak")),
    ):
        response = client.get(
            "/web-control/owner-snapshot",
            headers={"X-Operator-Token": "owner-secret"},
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "Owner dashboard snapshot is temporarily unavailable."
    assert "secret.internal" not in response.text
    assert "api_key" not in response.text

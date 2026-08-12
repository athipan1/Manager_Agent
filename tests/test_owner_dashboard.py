from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


FULL_OWNER_SNAPSHOT = {
    "schemaVersion": "dashboard-snapshot.v2",
    "generatedAt": "2026-08-12T17:00:00Z",
    "workflow": {
        "runId": 31621024738,
        "runNumber": 776,
        "conclusion": "success",
    },
    "runtime": {
        "mode": "PAPER",
        "brokerMode": "ALPACA",
        "flow": "hourly_portfolio_cycle",
    },
    "account": {
        "cash": 12500.25,
        "equity": 15120.75,
        "buyingPower": 25000.50,
        "status": "ACTIVE",
        "lastSyncedAt": "2026-08-12T17:00:00Z",
        "valuesMasked": False,
    },
    "summary": {
        "positionCount": 1,
        "openOrderCount": 0,
        "executionStatus": "not_attempted",
        "executionReason": "no_trade",
    },
    "positions": [
        {
            "symbol": "AAPL",
            "quantity": 2,
            "averageCost": 200.0,
            "currentPrice": 205.0,
            "marketValue": 410.0,
            "unrealizedPnL": 10.0,
            "bucket": "core",
            "protection": {
                "status": "protected",
                "hasStopLoss": True,
                "hasTakeProfit": False,
                "hasBracket": False,
            },
            "valuesMasked": False,
        }
    ],
    "openOrders": [],
    "signals": [],
    "privacy": {"mode": "full", "valuesMasked": False},
    "error": None,
}


def _configure(monkeypatch, tmp_path: Path) -> Path:
    path = tmp_path / "owner-snapshot.json"
    monkeypatch.setenv("WEB_CONTROL_OPERATOR_TOKEN", "owner-secret")
    monkeypatch.setenv("OWNER_SNAPSHOT_PUBLISH_TOKEN", "publisher-secret")
    monkeypatch.setenv("OWNER_SNAPSHOT_STORE_PATH", str(path))
    return path


def _publish(client: TestClient, payload=None):
    return client.post(
        "/web-control/owner-snapshot/publish",
        headers={"X-Owner-Snapshot-Token": "publisher-secret"},
        json=payload or FULL_OWNER_SNAPSHOT,
    )


def test_owner_snapshot_requires_operator_token(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.get("/web-control/owner-snapshot")

    assert response.status_code == 401


def test_owner_snapshot_requires_publisher_token(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.post(
        "/web-control/owner-snapshot/publish",
        json=FULL_OWNER_SNAPSHOT,
    )

    assert response.status_code == 401


def test_publish_then_read_owner_snapshot_from_github_actions(monkeypatch, tmp_path):
    store_path = _configure(monkeypatch, tmp_path)
    client = TestClient(app)

    published = _publish(client)
    assert published.status_code == 200
    assert published.json()["status"] == "stored"
    assert published.json()["source"] == "github-actions"
    assert published.json()["workflowRunId"] == 31621024738
    assert store_path.exists()

    response = client.get(
        "/web-control/owner-snapshot",
        headers={"X-Operator-Token": "owner-secret"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schemaVersion"] == "dashboard-snapshot.v1"
    assert body["account"]["cash"] == 12500.25
    assert body["account"]["equity"] == 15120.75
    assert body["account"]["buyingPower"] == 25000.5
    assert body["positions"][0]["marketValue"] == 410.0
    assert body["summary"]["dataSource"] == "github-actions-owner-snapshot"
    assert response.headers["cache-control"] == "no-store, max-age=0"
    assert response.headers["x-privacy-mode"] == "owner-authenticated"
    assert response.headers["x-owner-snapshot-source"] == "github-actions"
    assert response.headers["x-owner-snapshot-run-id"] == "31621024738"


def test_owner_snapshot_does_not_fallback_to_live_dependencies(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.get(
        "/web-control/owner-snapshot",
        headers={"X-Operator-Token": "owner-secret"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "No GitHub Actions owner snapshot has been published yet."


def test_publish_rejects_masked_or_empty_account_values(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    client = TestClient(app)
    masked = {
        **FULL_OWNER_SNAPSHOT,
        "account": {
            **FULL_OWNER_SNAPSHOT["account"],
            "cash": None,
            "equity": None,
            "buyingPower": None,
            "valuesMasked": True,
        },
        "privacy": {"mode": "masked", "valuesMasked": True},
    }

    response = _publish(client, masked)

    assert response.status_code == 422


def test_publish_rejects_secret_fields(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    client = TestClient(app)
    payload = {**FULL_OWNER_SNAPSHOT, "api_key": "must-not-be-stored"}

    response = _publish(client, payload)

    assert response.status_code == 422
    assert "must-not-be-stored" not in response.text


def test_publish_rejects_older_workflow_run(monkeypatch, tmp_path):
    _configure(monkeypatch, tmp_path)
    client = TestClient(app)
    assert _publish(client).status_code == 200
    older = {
        **FULL_OWNER_SNAPSHOT,
        "workflow": {**FULL_OWNER_SNAPSHOT["workflow"], "runId": 31621024737},
        "generatedAt": "2026-08-12T16:00:00Z",
    }

    response = _publish(client, older)

    assert response.status_code == 409

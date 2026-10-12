import pytest

from scripts.prepare_database_positions import fetch_runtime_state, post_database_snapshot, unwrap


def test_unwrap_returns_data_payload():
    assert unwrap({"data": [1, 2]}) == [1, 2]
    assert unwrap([3]) == [3]


def test_fetch_runtime_state(monkeypatch):
    calls = []

    def fake_request(base_url, path, **kwargs):
        calls.append((base_url, path, kwargs.get("api_key")))
        if path == "/account":
            return {"data": {"cash": "1000"}}
        if path == "/positions":
            return {"data": [{"symbol": "ACGL"}]}
        if path == "/orders":
            return {"data": [{"symbol": "ACGL"}]}
        return {}

    monkeypatch.setattr("scripts.prepare_database_positions.request_json", fake_request)
    state = fetch_runtime_state("http://runtime", "key")

    assert state["account"] == {"cash": "1000"}
    assert state["positions"] == [{"symbol": "ACGL"}]
    assert state["open_orders"] == [{"symbol": "ACGL"}]
    assert calls == [
        ("http://runtime", "/account", "key"),
        ("http://runtime", "/positions", "key"),
        ("http://runtime", "/orders", "key"),
    ]


def test_post_database_snapshot(monkeypatch):
    captured = []

    def fake_request(base_url, path, **kwargs):
        captured.append({"base_url": base_url, "path": path, "payload": kwargs.get("payload"), "api_key": kwargs.get("api_key")})
        return {"status": "success", "data": {"positions_synced": 1}}

    monkeypatch.setattr("scripts.prepare_database_positions.request_json", fake_request)
    result = post_database_snapshot(
        "http://database",
        "1",
        {"account": {"data": {"cash": "1000"}}, "positions": [{"symbol": "ACGL"}], "open_orders": []},
        "db-key",
    )

    assert result["response"]["status"] == "success"
    assert captured[0]["base_url"] == "http://database"
    assert captured[0]["path"] == "/broker-sync/snapshot"
    assert captured[0]["api_key"] == "db-key"
    assert captured[0]["payload"]["account_id"] == 1
    assert captured[0]["payload"]["positions"] == [{"symbol": "ACGL"}]
    assert captured[0]["payload"]["summary"]["position_count"] == 1


@pytest.mark.parametrize("invalid", [
    {"status": "error", "http_status": 401, "body": "unauthorized"},
    {"status": "success", "data": {"ACGL": {"qty": "1"}}},
    {"status": "success", "data": ["ACGL"]},
    {"status": "success", "data": None},
])
def test_fetch_runtime_state_rejects_invalid_positions(monkeypatch, invalid):
    def fake_request(base_url, path, **kwargs):
        if path == "/account":
            return {"status": "success", "data": {"cash": "1000"}}
        if path == "/positions":
            return invalid
        raise AssertionError("Invalid positions must stop before fetching orders")

    monkeypatch.setattr("scripts.prepare_database_positions.request_json", fake_request)
    with pytest.raises(ValueError, match="/positions"):
        fetch_runtime_state("http://execution", "key")


def test_post_database_snapshot_rejects_broker_error_before_post(monkeypatch):
    def should_never_post(*args, **kwargs):
        raise AssertionError("Unverified broker payload must not be persisted")

    monkeypatch.setattr("scripts.prepare_database_positions.request_json", should_never_post)
    with pytest.raises(ValueError, match="/positions"):
        post_database_snapshot(
            "http://database", "1",
            {"account": {"cash": "1000"}, "positions": {"status": "error"}, "open_orders": []},
            "db-key",
        )


def test_main_reports_fail_closed_and_skips_snapshot(monkeypatch, tmp_path):
    from scripts.prepare_database_positions import main

    def fake_request(base_url, path, **kwargs):
        if path == "/account":
            return {"status": "success", "data": {"cash": "1000"}}
        if path == "/positions":
            return {"status": "error", "http_status": 401}
        raise AssertionError("No downstream request allowed")

    monkeypatch.setattr("scripts.prepare_database_positions.request_json", fake_request)
    report = tmp_path / "position-prepare.json"
    assert main(["--output-json", str(report)]) == 1
    import json
    data = json.loads(report.read_text())
    assert data["snapshot_written"] is False
    assert data["status"] == "error"


def test_fetch_runtime_state_rejects_invalid_account_before_positions(monkeypatch):
    def fake_request(base_url, path, **kwargs):
        if path == "/account":
            return {"status": "success", "data": {"cash": ""}}
        raise AssertionError("Invalid account must block downstream requests")
    monkeypatch.setattr("scripts.prepare_database_positions.request_json", fake_request)
    with pytest.raises(ValueError, match="/account"):
        fetch_runtime_state("http://execution", "key")


def test_fetch_runtime_state_rejects_malformed_orders(monkeypatch):
    def fake_request(base_url, path, **kwargs):
        if path == "/account":
            return {"status": "success", "data": {"cash": "1000"}}
        if path == "/positions":
            return {"status": "success", "data": [{"symbol": "ACGL"}]}
        if path == "/orders":
            return {"status": "error", "http_status": 401}
        raise AssertionError(path)
    monkeypatch.setattr("scripts.prepare_database_positions.request_json", fake_request)
    with pytest.raises(ValueError, match="/orders"):
        fetch_runtime_state("http://execution", "key")

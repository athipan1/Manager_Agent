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

    assert state["account"] == {"data": {"cash": "1000"}}
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

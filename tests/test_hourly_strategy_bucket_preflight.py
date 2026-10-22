import json
from pathlib import Path

import pytest

from scripts import hourly_paper_preflight as preflight


def _registry(path: Path, assignments=None) -> Path:
    payload = {
        "schema_version": "strategy-bucket-assignments.v1",
        "account_id": 1,
        "source": "manager-strategy-bucket-v3-held-position-migration",
        "reason": "Restore confirmed strategy ownership for Paper holdings.",
        "assignments": assignments
        or {
            "ACGL": "value_rebound",
            "ADBE": "value_rebound",
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class FakeAssignmentClient:
    existing = {}
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def request(
        self,
        path,
        *,
        method="GET",
        payload=None,
        correlation_id,
    ):
        self.__class__.calls.append(
            {
                "path": path,
                "method": method,
                "payload": payload,
                "correlation_id": correlation_id,
            }
        )
        if method == "POST":
            for row in payload["assignments"]:
                self.__class__.existing[row["symbol"]] = row["strategy_bucket"]
            return {
                "data": {
                    "updated_count": len(payload["assignments"]),
                    "requested_count": len(payload["assignments"]),
                }
            }
        return {
            "data": {
                "assignments": [
                    {
                        "account_id": 1,
                        "symbol": symbol,
                        "strategy_bucket": bucket,
                    }
                    for symbol, bucket in sorted(self.__class__.existing.items())
                ]
            }
        }


def _install_fake_client(monkeypatch, existing=None):
    FakeAssignmentClient.existing = dict(existing or {})
    FakeAssignmentClient.calls = []
    monkeypatch.setattr(
        preflight.runtime,
        "JsonHttpClient",
        FakeAssignmentClient,
    )


def test_missing_approved_assignments_are_seeded_and_verified(
    monkeypatch,
    tmp_path,
):
    _install_fake_client(monkeypatch)
    registry = _registry(tmp_path / "assignments.json")

    result = preflight.ensure_strategy_bucket_assignments(
        base_url="https://database.example",
        api_key="database-key",
        correlation_id="cycle-1",
        account_id=1,
        registry_path=registry,
    )

    assert result == {
        "status": "verified",
        "account_id": 1,
        "approved_assignment_count": 2,
        "seeded_count": 2,
        "seeded_symbols": ["ACGL", "ADBE"],
        "conflict_count": 0,
    }
    post_calls = [
        call for call in FakeAssignmentClient.calls if call["method"] == "POST"
    ]
    assert len(post_calls) == 1
    assert post_calls[0]["path"] == "/accounts/1/position-buckets/bulk"
    assert {
        row["symbol"]: row["strategy_bucket"]
        for row in post_calls[0]["payload"]["assignments"]
    } == {
        "ACGL": "value_rebound",
        "ADBE": "value_rebound",
    }


def test_existing_matching_assignments_are_not_rewritten(
    monkeypatch,
    tmp_path,
):
    _install_fake_client(
        monkeypatch,
        {
            "ACGL": "value_rebound",
            "ADBE": "value_rebound",
        },
    )
    registry = _registry(tmp_path / "assignments.json")

    result = preflight.ensure_strategy_bucket_assignments(
        base_url="https://database.example",
        api_key="database-key",
        correlation_id="cycle-1",
        account_id=1,
        registry_path=registry,
    )

    assert result["seeded_count"] == 0
    assert not [
        call for call in FakeAssignmentClient.calls if call["method"] == "POST"
    ]


def test_conflicting_assignment_fails_closed_without_overwrite(
    monkeypatch,
    tmp_path,
):
    _install_fake_client(
        monkeypatch,
        {
            "ACGL": "quality_growth",
        },
    )
    registry = _registry(tmp_path / "assignments.json")

    with pytest.raises(
        preflight.RuntimeSafetyError,
        match="conflicting strategy bucket assignments for: ACGL",
    ):
        preflight.ensure_strategy_bucket_assignments(
            base_url="https://database.example",
            api_key="database-key",
            correlation_id="cycle-1",
            account_id=1,
            registry_path=registry,
        )

    assert not [
        call for call in FakeAssignmentClient.calls if call["method"] == "POST"
    ]


def test_registry_account_must_match_runtime_account(
    monkeypatch,
    tmp_path,
):
    _install_fake_client(monkeypatch)
    registry = _registry(tmp_path / "assignments.json")

    with pytest.raises(
        preflight.RuntimeSafetyError,
        match="does not match DEFAULT_ACCOUNT_ID",
    ):
        preflight.ensure_strategy_bucket_assignments(
            base_url="https://database.example",
            api_key="database-key",
            correlation_id="cycle-1",
            account_id=2,
            registry_path=registry,
        )


def test_unknown_bucket_in_registry_is_rejected(tmp_path):
    registry = _registry(
        tmp_path / "assignments.json",
        {"ACGL": "unknown_bucket"},
    )

    with pytest.raises(
        preflight.RuntimeSafetyError,
        match="invalid assignment",
    ):
        preflight._load_strategy_bucket_registry(registry)


def _railway_responses():
    return {
        "/health": {
            "data": {
                "database_connection": "connected",
                "dev_mode": False,
                "trading_mode": "PAPER",
                "database_emergency_halt": False,
            }
        },
        "/ready": {"data": {"ready": True}},
        "/version": {"data": {"agent_type": "database", "version": "1.1.0"}},
    }


def _check_database():
    return preflight._check_railway_database_compatible(
        base_url="https://database.example",
        api_key="database-key",
        correlation_id="cycle-1",
    )


def test_transient_disconnected_health_recovers_with_fresh_verified_probe(monkeypatch):
    responses = _railway_responses()
    calls = []
    sleeps = []

    def request(self, path, **kwargs):
        calls.append(path)
        if path == "/health" and calls.count("/health") == 1:
            return {"data": {**responses[path]["data"], "database_connection": "disconnected"}}
        return responses[path]

    monkeypatch.setattr(preflight.runtime.JsonHttpClient, "request", request)
    monkeypatch.setattr(preflight.time, "sleep", sleeps.append)

    result = _check_database()

    assert result["ready"] is True
    assert calls == ["/health", "/health", "/ready", "/version"]
    assert sleeps == [1]


def test_transient_ready_http_503_restarts_full_probe(monkeypatch):
    responses = _railway_responses()
    calls = []
    sleeps = []

    def request(self, path, **kwargs):
        calls.append(path)
        if path == "/ready" and calls.count("/ready") == 1:
            raise preflight.RuntimeSafetyError(
                "Railway Database_Agent GET /ready failed after bounded retries: HTTP 503."
            )
        return responses[path]

    monkeypatch.setattr(preflight.runtime.JsonHttpClient, "request", request)
    monkeypatch.setattr(preflight.time, "sleep", sleeps.append)

    assert _check_database()["health"] == "connected"
    assert calls == ["/health", "/ready", "/health", "/ready", "/version"]
    assert sleeps == [1]


@pytest.mark.parametrize("failure", ["disconnected", "not_ready"])
def test_database_remains_fail_closed_after_bounded_transient_retries(
    monkeypatch, failure
):
    responses = _railway_responses()
    if failure == "disconnected":
        responses["/health"]["data"]["database_connection"] = "disconnected"
    else:
        responses["/ready"]["data"]["ready"] = False
    calls = []
    sleeps = []

    def request(self, path, **kwargs):
        calls.append(path)
        return responses[path]

    monkeypatch.setattr(preflight.runtime.JsonHttpClient, "request", request)
    monkeypatch.setattr(preflight.time, "sleep", sleeps.append)

    with pytest.raises(preflight.RuntimeSafetyError, match="did not confirm|readiness check failed"):
        _check_database()

    assert calls.count("/health") == preflight.DATABASE_READINESS_CONSISTENCY_ATTEMPTS
    assert "/version" not in calls
    assert sleeps == [1, 2]


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("database_emergency_halt", True, "emergency halt"),
        ("dev_mode", True, "DATABASE_DEV_MODE=false"),
        ("trading_mode", "LIVE", "TRADING_MODE=PAPER"),
    ],
)
def test_database_policy_failures_never_retry(monkeypatch, field, value, error):
    responses = _railway_responses()
    responses["/health"]["data"][field] = value
    calls = []
    sleeps = []

    def request(self, path, **kwargs):
        calls.append(path)
        return responses[path]

    monkeypatch.setattr(preflight.runtime.JsonHttpClient, "request", request)
    monkeypatch.setattr(preflight.time, "sleep", sleeps.append)

    with pytest.raises(preflight.RuntimeSafetyError, match=error):
        _check_database()
    assert calls == ["/health"]
    assert sleeps == []


def test_database_authentication_failure_never_retry(monkeypatch):
    calls = []
    sleeps = []

    def request(self, path, **kwargs):
        calls.append(path)
        raise preflight.RuntimeSafetyError(
            "Railway Database_Agent GET /health failed after bounded retries: HTTP 401."
        )

    monkeypatch.setattr(preflight.runtime.JsonHttpClient, "request", request)
    monkeypatch.setattr(preflight.time, "sleep", sleeps.append)

    with pytest.raises(preflight.RuntimeSafetyError, match="HTTP 401"):
        _check_database()
    assert calls == ["/health"]
    assert sleeps == []

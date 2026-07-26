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

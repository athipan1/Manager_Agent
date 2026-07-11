import datetime

from app.workflows.gated_guarded_discovery_workflow import (
    database_snapshot_age_seconds,
)


def test_database_snapshot_age_seconds_uses_nested_capture_timestamp():
    now = datetime.datetime(
        2026,
        7,
        11,
        12,
        0,
        tzinfo=datetime.UTC,
    )
    database_sync = {
        "latest_snapshot": {
            "captured_at": "2026-07-11T11:59:15Z",
        }
    }

    assert database_snapshot_age_seconds(
        database_sync,
        now=now,
    ) == 45.0


def test_database_snapshot_age_seconds_returns_none_without_timestamp():
    assert database_snapshot_age_seconds({"mismatch": {}}) is None

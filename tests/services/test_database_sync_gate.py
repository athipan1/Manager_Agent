from app.services.database_sync_gate import (
    database_sync_allows_automation,
    database_sync_block_reason,
    database_sync_blocked_execution,
    database_sync_status,
    database_sync_summary,
)


def sync_payload(status, action="refresh_broker_sync"):
    return {
        "mismatch": {
            "is_synced": status == "synced",
            "summary": {
                "status": status,
                "severity": "ok" if status == "synced" else "warning",
                "recommended_action": action,
            },
            "diagnostics": {
                "positions": {"missing_in_database": ["AAPL"]},
            },
        }
    }


def test_database_sync_allows_synced_and_legacy_unknown_payloads():
    assert database_sync_allows_automation({}) is True
    assert database_sync_allows_automation(None) is True
    assert database_sync_allows_automation(sync_payload("synced", "none")) is True
    assert database_sync_status(sync_payload("synced", "none")) == "synced"


def test_database_sync_blocks_known_unsafe_statuses():
    for status in ["mismatch", "no_snapshot", "unavailable", "error", "failed"]:
        payload = sync_payload(status)
        assert database_sync_allows_automation(payload) is False
        assert database_sync_summary(payload)["status"] == status


def test_database_sync_blocked_execution_is_report_ready():
    payload = sync_payload("mismatch", "refresh_broker_sync")
    result = database_sync_blocked_execution(payload)

    assert result["status"] == "blocked"
    assert "recommended_action=refresh_broker_sync" in result["reason"]
    assert result["database_sync_summary"]["status"] == "mismatch"
    assert result["database_sync"] == payload


def test_database_sync_block_reason_defaults_when_summary_missing():
    assert database_sync_block_reason({}) == "Database/Broker sync status is unknown; recommended_action=refresh_broker_sync."

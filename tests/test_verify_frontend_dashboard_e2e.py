import pytest

from scripts.verify_frontend_dashboard_e2e import assert_safe, validate_snapshot


def valid_snapshot():
    return {
        "schemaVersion": "dashboard-snapshot.v1",
        "generatedAt": "2026-07-21T10:00:00Z",
        "mode": "PAPER",
        "brokerMode": "SIMULATOR",
        "flow": "portfolio_review",
        "account": {},
        "positions": [],
        "openOrders": [],
        "curatorSignals": [],
        "summary": {},
    }


def test_e2e_validator_accepts_safe_contract():
    validate_snapshot(valid_snapshot())


def test_e2e_validator_rejects_sensitive_nested_keys():
    with pytest.raises(AssertionError, match="Sensitive key"):
        assert_safe({"summary": {"database_url": "hidden"}})


def test_e2e_validator_rejects_wrong_mode_or_schema():
    snapshot = valid_snapshot()
    snapshot["schemaVersion"] = "dashboard-snapshot.v2"
    with pytest.raises(AssertionError, match="v1"):
        validate_snapshot(snapshot)

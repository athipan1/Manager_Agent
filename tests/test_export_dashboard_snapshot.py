import json
from datetime import datetime, timezone

import pytest

from scripts.export_dashboard_snapshot import TOP_LEVEL_KEYS, build_snapshot


NOW = datetime(2026, 7, 30, 1, 0, tzinfo=timezone.utc)


def report(**overrides):
    payload = {
        "generated_at": "2026-07-30T00:00:00Z",
        "mode": "ALPACA_PAPER",
        "broker_mode": "ALPACA",
        "flow": "hourly_portfolio_cycle",
        "cycle": {
            "id": "cycle-100",
            "status": "success",
            "marketMode": "REGULAR",
            "candidateCount": 1,
            "selectedSymbols": ["ACGL"],
            "executionAttempted": False,
            "executionStatus": "not_attempted",
            "executionReason": "risk_rejected",
            "partialFillDetected": False,
        },
        "phases": [
            {"name": "preflight", "status": "success", "message": None},
            {"name": "scanner", "status": "success", "message": "candidate found"},
            {"name": "backtest", "status": "success", "message": None},
            {"name": "risk", "status": "failure", "message": "risk rejected"},
            {"name": "execution", "status": "not_attempted", "message": "risk rejected"},
        ],
        "account": {"cash": "48155.50", "equity": "71784.67", "buyingPower": "275290.36", "status": "ACTIVE"},
        "positions": [{
            "symbol": "ACGL", "qty": "54", "avg_entry_price": "104.20",
            "current_price": "104.155", "market_value": "5624.37",
            "unrealized_pl": "-2.43", "strategy_bucket": "value_rebound",
            "account_id": "must-not-export",
        }],
        "openOrders": [{
            "id": "must-not-export", "client_order_id": "must-not-export",
            "symbol": "ACGL", "side": "sell", "qty": "54", "type": "limit",
            "order_class": "bracket", "status": "new", "limit_price": "112.84",
        }],
        "signals": [{"symbol": "ACGL", "status": "success", "skill_name": "Hourly Signal", "reason": "score passed", "confidence": 0.63}],
        "warnings": [],
        "error": None,
    }
    payload.update(overrides)
    return payload


def workflow(conclusion="success", run_id=123, run_number=100):
    return {
        "runId": run_id,
        "runNumber": run_number,
        "runUrl": f"https://github.com/athipan1/Manager_Agent/actions/runs/{run_id}",
        "eventName": "schedule",
        "status": "completed",
        "conclusion": conclusion,
        "startedAt": "2026-07-29T23:53:00Z",
        "completedAt": "2026-07-30T00:00:00Z",
    }


def test_export_snapshot_success_v2_full_mode():
    snapshot = build_snapshot(report(), workflow_metadata=workflow(), privacy_mode="full", now=NOW)
    assert snapshot["schemaVersion"] == "dashboard-snapshot.v2"
    assert snapshot["workflow"]["durationSeconds"] == 420
    assert snapshot["runtime"] == {
        "mode": "ALPACA_PAPER",
        "brokerMode": "ALPACA",
        "dryRun": False,
        "liveTradingEnabled": False,
        "flow": "hourly_portfolio_cycle",
    }
    assert snapshot["account"]["cash"] == 48155.5
    assert snapshot["positions"][0]["symbol"] == "ACGL"
    assert snapshot["lastSuccessfulRun"]["runId"] == 123


def test_no_candidate_and_skipped_phases_are_preserved():
    payload = report()
    payload["cycle"].update({"candidateCount": 0, "selectedSymbols": [], "executionReason": "no_preselected_backtest_symbols"})
    payload["phases"] = [
        {"name": "scanner", "status": "success", "message": "No candidate passed the score threshold"},
        {"name": "backtest", "status": "skipped", "message": "No scanner symbols"},
        {"name": "risk", "status": "skipped", "message": "No candidate"},
        {"name": "execution", "status": "not_attempted", "message": "No approved trade"},
    ]
    snapshot = build_snapshot(payload, workflow_metadata=workflow(), privacy_mode="masked", now=NOW)
    assert snapshot["summary"]["candidateCount"] == 0
    assert [row["status"] for row in snapshot["phases"]] == ["success", "skipped", "skipped", "not_attempted"]


@pytest.mark.parametrize(
    ("execution_status", "reason", "attempted", "partial"),
    [
        ("not_attempted", "risk_rejected", False, False),
        ("submitted", "orders_accepted", True, False),
        ("failure", "broker_rejected", True, False),
        ("partial_fill", "partially_filled", True, True),
    ],
)
def test_execution_scenarios(execution_status, reason, attempted, partial):
    payload = report()
    payload["cycle"].update({
        "executionStatus": execution_status,
        "executionReason": reason,
        "executionAttempted": attempted,
        "partialFillDetected": partial,
    })
    snapshot = build_snapshot(payload, workflow_metadata=workflow(), privacy_mode="masked", now=NOW)
    assert snapshot["cycle"]["executionStatus"] == execution_status
    assert snapshot["cycle"]["executionAttempted"] is attempted
    assert snapshot["cycle"]["partialFillDetected"] is partial


@pytest.mark.parametrize(
    ("conclusion", "cycle_status", "error_code"),
    [
        ("failure", "failure", "HOURLY_WORKFLOW_FAILED"),
        ("cancelled", "cancelled", "HOURLY_WORKFLOW_CANCELLED"),
        ("timed_out", "failure", "HOURLY_WORKFLOW_FAILED"),
        ("action_required", "failure", "HOURLY_WORKFLOW_FAILED"),
        ("stale", "failure", "HOURLY_WORKFLOW_FAILED"),
    ],
)
def test_workflow_failure_fallbacks(conclusion, cycle_status, error_code):
    snapshot = build_snapshot({}, workflow_metadata=workflow(conclusion), privacy_mode="status-only", now=NOW)
    assert snapshot["cycle"]["status"] == cycle_status
    assert snapshot["error"]["code"] == error_code
    assert snapshot["positions"] == []


def test_missing_or_malformed_artifact_uses_safe_fallback():
    snapshot = build_snapshot({}, workflow_metadata=workflow("failure"), privacy_mode="masked", malformed_artifact=True, now=NOW)
    assert snapshot["error"]["code"] == "MALFORMED_HOURLY_ARTIFACT"
    assert "parsed" in snapshot["warnings"][0]


@pytest.mark.parametrize("mode", ["full", "masked", "status-only"])
def test_privacy_modes(mode):
    snapshot = build_snapshot(report(), workflow_metadata=workflow(), privacy_mode=mode, now=NOW)
    assert snapshot["privacy"]["mode"] == mode
    if mode == "full":
        assert snapshot["account"]["cash"] == 48155.5
    else:
        assert snapshot["account"]["cash"] is None
        assert snapshot["account"]["valuesMasked"] is True
    if mode == "status-only":
        assert snapshot["positions"] == []
        assert snapshot["openOrders"] == []
        assert snapshot["signals"] == []


def test_secret_redaction_and_order_identifiers_are_not_exported():
    payload = report(warnings=["Authorization: Bearer abc123"], error={"code": "FAIL", "message": "operator_token=secret"})
    snapshot = build_snapshot(payload, workflow_metadata=workflow(), privacy_mode="full", now=NOW)
    serialized = json.dumps(snapshot).lower()
    assert "abc123" not in serialized
    assert "operator_token" not in serialized
    assert "client_order_id" not in serialized
    assert "must-not-export" not in serialized


def test_last_successful_run_is_preserved_after_failure():
    previous = build_snapshot(report(), workflow_metadata=workflow("success", 123, 99), privacy_mode="masked", now=NOW)
    failed = build_snapshot({}, workflow_metadata=workflow("failure", 124, 100), previous_snapshot=previous, privacy_mode="masked", now=NOW)
    assert failed["lastSuccessfulRun"] == previous["lastSuccessfulRun"]
    assert failed["workflow"]["runId"] == 124


def test_freshness_and_timezone_are_deterministic():
    fresh = build_snapshot(report(), workflow_metadata=workflow(), privacy_mode="masked", now=NOW)
    stale = build_snapshot(report(generated_at="2026-07-29T22:00:00+00:00"), workflow_metadata=workflow(), privacy_mode="masked", now=NOW)
    assert fresh["generatedAt"].endswith("Z")
    assert fresh["freshness"]["ageMinutes"] == 60
    assert fresh["freshness"]["isStale"] is False
    assert stale["freshness"]["isStale"] is True


def test_non_finite_numbers_are_removed_and_json_is_serializable():
    payload = report(account={"cash": "NaN", "equity": "Infinity", "buyingPower": "-Infinity"})
    snapshot = build_snapshot(payload, workflow_metadata=workflow(), privacy_mode="full", now=NOW)
    assert snapshot["account"]["cash"] is None
    assert snapshot["account"]["equity"] is None
    assert snapshot["account"]["buyingPower"] is None
    json.dumps(snapshot, allow_nan=False)


def test_public_snapshot_uses_top_level_allowlist_only():
    snapshot = build_snapshot(report(private_service_url="http://manager-agent:8000"), workflow_metadata=workflow(), privacy_mode="masked", now=NOW)
    assert set(snapshot) == TOP_LEVEL_KEYS
    assert "private_service_url" not in json.dumps(snapshot)

from datetime import datetime, timezone

import pytest

from scripts.export_dashboard_snapshot import build_snapshot
from scripts.normalize_broker_sync_owner_report import normalize_report


NOW = datetime(2026, 8, 14, 0, 0, tzinfo=timezone.utc)


def envelope(data, *, status="success", error=None):
    return {
        "status": status,
        "agent_type": "test",
        "version": "1.0.0",
        "schema_version": "1.0",
        "data": data,
        "error": error,
    }


def broker_sync_report(**overrides):
    payload = {
        "generated_at": "2026-08-13T16:33:32+00:00",
        "broker_mode": "ALPACA",
        "reconcile": envelope(
            {
                "ok": True,
                "database_sync": {"status": "success", "http_status": 200},
            }
        ),
        "database_sync_status": envelope(
            {
                "has_snapshot": True,
                "mismatch": {
                    "is_synced": True,
                    "mismatch_count": 0,
                    "mismatches": [],
                },
            }
        ),
        "broker_snapshot": {
            "account": envelope(
                {
                    "broker": "alpaca",
                    "paper": True,
                    "account_id": "private-broker-id",
                    "status": "ACTIVE",
                    "currency": "USD",
                    "cash": "1000.25",
                    "buying_power": "4000.50",
                    "equity": "1250.75",
                    "portfolio_value": "1250.75",
                }
            ),
            "positions": envelope(
                [
                    {
                        "symbol": "ACGL",
                        "qty": "2",
                        "avg_entry_price": "100.00",
                        "current_price": "105.00",
                        "market_value": "210.00",
                        "unrealized_pl": "10.00",
                    }
                ]
            ),
            "orders": envelope(
                [
                    {
                        "symbol": "ACGL",
                        "side": "sell",
                        "qty": "2",
                        "type": "limit",
                        "order_class": "simple",
                        "status": "new",
                        "limit_price": "110.00",
                    }
                ]
            ),
        },
    }
    payload.update(overrides)
    return payload


def workflow_metadata(run_id=31721071929):
    return {
        "runId": run_id,
        "runNumber": 565,
        "runUrl": f"https://github.com/athipan1/Manager_Agent/actions/runs/{run_id}",
        "workflowName": "Broker Sync Check",
        "eventName": "schedule",
        "status": "completed",
        "conclusion": "success",
        "startedAt": "2026-08-13T16:31:03Z",
        "completedAt": "2026-08-13T16:33:41Z",
    }


def test_broker_sync_normalizes_to_paper_owner_snapshot_input():
    normalized = normalize_report(broker_sync_report())

    assert normalized["runtime"] == {
        "mode": "PAPER",
        "brokerMode": "ALPACA",
        "dryRun": False,
        "liveTradingEnabled": False,
        "flow": "broker_sync_check",
    }
    assert normalized["cycle"]["status"] == "success"
    assert normalized["cycle"]["executionReason"] == "read_only_broker_sync"
    assert normalized["account"]["paper"] is True
    assert normalized["positions"][0]["symbol"] == "ACGL"
    assert normalized["openOrders"][0]["symbol"] == "ACGL"


def test_broker_sync_exports_value_bearing_dashboard_snapshot():
    normalized = normalize_report(broker_sync_report())
    snapshot = build_snapshot(
        normalized,
        workflow_metadata=workflow_metadata(),
        privacy_mode="full",
        now=NOW,
    )

    assert snapshot["schemaVersion"] == "dashboard-snapshot.v2"
    assert snapshot["runtime"]["mode"] == "PAPER"
    assert snapshot["runtime"]["brokerMode"] == "ALPACA"
    assert snapshot["runtime"]["flow"] == "broker_sync_check"
    assert snapshot["privacy"] == {"mode": "full", "valuesMasked": False}
    assert snapshot["account"]["cash"] == 1000.25
    assert snapshot["account"]["equity"] == 1250.75
    assert snapshot["account"]["buyingPower"] == 4000.50
    assert snapshot["positions"][0]["quantity"] == 2.0
    assert snapshot["openOrders"][0]["quantity"] == 2.0
    assert snapshot["lastSuccessfulRun"]["runId"] == 31721071929


def test_broker_sync_rejects_live_account():
    payload = broker_sync_report()
    payload["broker_snapshot"]["account"]["data"]["paper"] = False

    with pytest.raises(ValueError, match="Paper accounts"):
        normalize_report(payload)


def test_broker_sync_rejects_database_mismatch():
    payload = broker_sync_report()
    payload["database_sync_status"]["data"]["mismatch"]["is_synced"] = False

    with pytest.raises(ValueError, match="does not match"):
        normalize_report(payload)


def test_broker_sync_rejects_missing_account_values():
    payload = broker_sync_report()
    account = payload["broker_snapshot"]["account"]["data"]
    account["cash"] = None
    account["equity"] = None
    account["buying_power"] = None

    with pytest.raises(ValueError, match="does not contain account values"):
        normalize_report(payload)


def test_broker_sync_rejects_failed_broker_response():
    payload = broker_sync_report()
    payload["broker_snapshot"]["positions"] = envelope(
        [], status="error", error={"code": "BROKER_DOWN"}
    )

    with pytest.raises(ValueError, match="positions response is not successful"):
        normalize_report(payload)

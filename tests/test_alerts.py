import datetime

from app.alerts import AlertService


def test_queue_stuck_alert_emitted():
    service = AlertService()
    event = service.record_queue_status(
        queue_name="execution",
        oldest_age_seconds=999,
        pending_count=3,
        correlation_id="corr-queue",
    )
    assert event is not None
    assert event["alert_type"] == "queue_stuck"
    assert event["severity"] == "critical"
    assert event["metadata"]["pending_count"] == 3


def test_broker_database_mismatch_alert_emitted():
    service = AlertService()
    event = service.record_reconciliation_result(
        correlation_id="corr-recon",
        mismatch_count=2,
        metadata={"source": "reconciliation"},
    )
    assert event is not None
    assert event["alert_type"] == "broker_database_mismatch"
    assert event["severity"] == "critical"
    assert event["metadata"]["mismatch_count"] == 2


def test_readiness_stale_alert_emitted():
    service = AlertService()
    stale_time = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=10)).isoformat()
    readiness = {
        "required": True,
        "approved": False,
        "reason": "technical_walk_forward report is stale",
        "technical": {"fresh": False, "timestamp": stale_time, "passed": True},
        "fundamental": {"fresh": True, "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(), "passed": True},
    }
    events = service.record_readiness_result(correlation_id="corr-ready", symbol="AAPL", readiness=readiness)
    alert_types = {event["alert_type"] for event in events}
    assert "readiness_validation_stale" in alert_types
    assert "readiness_validation_rejected" in alert_types


def test_approval_reject_spike_alert_emitted(monkeypatch):
    monkeypatch.setattr("app.alerts._APPROVAL_REJECT_SPIKE_THRESHOLD", 2)
    service = AlertService()
    first = service.record_approval_reject(correlation_id="corr-1", symbol="AAPL", reason="reject 1")
    second = service.record_approval_reject(correlation_id="corr-2", symbol="MSFT", reason="reject 2")
    assert first is None
    assert second is not None
    assert second["alert_type"] == "approval_reject_spike"
    assert second["severity"] == "critical"

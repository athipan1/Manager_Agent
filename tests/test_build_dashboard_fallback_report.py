from scripts.build_dashboard_fallback_report import (
    minimal_report,
    retained_report,
)


def metadata(conclusion="skipped", workflow_name="Hourly Auto Trading"):
    return {
        "runId": 30520134021,
        "runNumber": 609,
        "runUrl": "https://github.com/athipan1/Manager_Agent/actions/runs/30520134021",
        "workflowName": workflow_name,
        "eventName": "schedule",
        "status": "completed",
        "conclusion": conclusion,
        "startedAt": "2026-07-30T06:36:46Z",
        "completedAt": "2026-07-30T06:36:47Z",
    }


def previous_snapshot(mode="PAPER"):
    return {
        "schemaVersion": "dashboard-snapshot.v2",
        "generatedAt": "2026-07-30T05:30:00Z",
        "runtime": {
            "mode": mode,
            "brokerMode": "ALPACA",
            "dryRun": False,
            "liveTradingEnabled": False,
            "flow": "hourly_portfolio_cycle",
        },
        "cycle": {
            "id": "hourly-paper-1",
            "status": "completed",
            "marketMode": "PORTFOLIO_REVIEW_ONLY",
            "candidateCount": 0,
            "selectedSymbols": [],
            "executionAttempted": False,
            "executionStatus": "not_attempted",
            "executionReason": "no_preselected_backtest_symbols",
            "partialFillDetected": False,
        },
        "phases": [{"name": "preflight", "status": "success", "message": None}],
        "account": {"cash": None, "equity": None, "buyingPower": None, "status": "ACTIVE"},
        "summary": {
            "positionCount": 1,
            "openOrderCount": 1,
            "candidateCount": 0,
            "executionStatus": "not_attempted",
            "executionReason": "no_preselected_backtest_symbols",
        },
        "positions": [{"symbol": "ACGL", "valuesMasked": True}],
        "openOrders": [{"symbol": "ACGL", "valuesMasked": True}],
        "signals": [{"symbol": "ACGL", "status": "hold"}],
        "warnings": [],
        "lastSuccessfulRun": {"runId": 123},
    }


def test_skipped_hourly_run_reports_paper_instead_of_unknown():
    report = minimal_report(metadata())
    assert report["runtime"]["mode"] == "PAPER"
    assert report["runtime"]["brokerMode"] == "ALPACA"
    assert report["runtime"]["dryRun"] is False
    assert report["runtime"]["liveTradingEnabled"] is False
    assert report["cycle"]["status"] == "skipped"
    assert report["cycle"]["executionReason"] == "scheduled_paper_cycle_not_authorized"
    assert report["error"] is None


def test_verified_previous_paper_data_is_retained_without_new_artifact():
    report = retained_report(previous_snapshot(), metadata())
    assert report["runtime"]["mode"] == "PAPER"
    assert report["cycle_status"] == "completed"
    assert report["positions"][0]["symbol"] == "ACGL"
    assert report["openOrders"][0]["symbol"] == "ACGL"
    assert report["signals"][0]["status"] == "hold"
    assert any("retained" in warning for warning in report["warnings"])


def test_legacy_alpaca_paper_mode_is_normalized():
    report = retained_report(previous_snapshot("ALPACA_PAPER"), metadata())
    assert report["mode"] == "PAPER"
    assert report["runtime"]["mode"] == "PAPER"
    assert report["runtime"]["dryRun"] is False


def test_unknown_previous_placeholder_is_not_retained():
    previous = previous_snapshot("UNKNOWN")
    previous["cycle"]["status"] = "unknown"
    previous["positions"] = []
    previous["openOrders"] = []
    previous["signals"] = []
    previous["lastSuccessfulRun"] = None
    report = retained_report(previous, metadata())
    assert report["runtime"]["mode"] == "PAPER"
    assert report["cycle_status"] == "skipped"
    assert report["positions"] == []


def test_failed_workflow_sets_safe_error_without_enabling_live_trading():
    report = minimal_report(metadata("failure", "Manual Alpaca Paper Trading"))
    assert report["runtime"]["liveTradingEnabled"] is False
    assert report["cycle_status"] == "failure"
    assert report["error"]["code"] == "HOURLY_WORKFLOW_FAILED"

import json
from pathlib import Path

from scripts.verify_paper_cycle_evidence import verify_artifact


def write_json(path: Path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


def build_artifacts(tmp_path: Path, *, partial_fill=False, drill_status="passed"):
    write_json(
        tmp_path / "hourly-preflight.json",
        {
            "status": "ready",
            "portfolio_cycle_id": "hourly-paper-hash-20260729T06",
            "market_mode": "REVIEW_AND_TRADE",
            "runtime": {
                "paper_automation": True,
                "broker_mode": "ALPACA",
                "dry_run": False,
                "paper_api_url_valid": True,
                "profit_decision_execution_enabled": False,
                "profit_auto_exit_all_enabled": False,
            },
            "alpaca_paper": {
                "account_ref": "abc123",
                "account_status": "ACTIVE",
            },
        },
    )
    write_json(
        tmp_path / "hourly-portfolio-cycle.json",
        {
            "status": "completed",
            "post_execution_reconciliation": {
                "ok": True,
                "database_sync": {"status": "success"},
            },
            "post_execution_protection": {
                "positions": [
                    {
                        "symbol": "AAPL",
                        "protection_status": "tp_sl_protected",
                        "unprotected_quantity": 0,
                    }
                ]
            },
            "submitted_order_statuses": [{"order_id": "paper-1", "status": "filled"}],
            "partial_fill_detected": partial_fill,
        },
    )
    write_json(
        tmp_path / "hourly-auto-trading-report.json",
        {"cycle_status": "completed"},
    )
    drill_checks = {
        name: True
        for name in (
            "initially_clear",
            "trip_confirmed",
            "policy_halted",
            "readiness_blocked",
            "risk_probe_rejected",
            "clear_confirmed",
            "readiness_restored",
        )
    }
    write_json(
        tmp_path / "emergency-halt-drill.json",
        {
            "status": drill_status,
            "checks": drill_checks,
        },
    )


def test_clean_paper_cycle_evidence_passes(tmp_path):
    build_artifacts(tmp_path)

    evidence = verify_artifact(
        artifact_dir=tmp_path,
        require_emergency_drill=True,
    )

    assert evidence["result"] == "success"
    assert evidence["failed_check_count"] == 0
    assert evidence["submitted_order_count"] == 1


def test_partial_fill_is_a_promotion_warning(tmp_path):
    build_artifacts(tmp_path, partial_fill=True)

    evidence = verify_artifact(
        artifact_dir=tmp_path,
        require_emergency_drill=True,
    )

    assert evidence["result"] == "warning"
    assert evidence["warnings"] == ["partial_fill_detected"]


def test_reconciliation_or_halt_drill_failure_fails_evidence(tmp_path):
    build_artifacts(tmp_path, drill_status="failed")
    cycle_path = tmp_path / "hourly-portfolio-cycle.json"
    cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
    cycle["post_execution_reconciliation"] = {
        "ok": False,
        "mismatch": {"summary": {"status": "mismatch"}},
    }
    write_json(cycle_path, cycle)

    evidence = verify_artifact(
        artifact_dir=tmp_path,
        require_emergency_drill=True,
    )

    assert evidence["result"] == "failure"
    assert "post_execution_reconciliation" in evidence["failed_checks"]
    assert "emergency_halt_drill" in evidence["failed_checks"]

import json

from scripts.build_hourly_operator_artifact import build_hourly_operator_artifact, main


def paper_preflight():
    return {
        "status": "ready",
        "portfolio_cycle_id": "hourly-paper-1",
        "market_mode": "PORTFOLIO_REVIEW_ONLY",
        "runtime": {"paper_automation": True, "broker_mode": "ALPACA", "dry_run": False},
    }


def cycle():
    return {
        "review": {"generated_at": "2026-07-26T19:45:30+00:00", "portfolio_cycle_id": "hourly-paper-1"},
        "candidate_cycle": {
            "execute_requested": False,
            "manager_response": {"status": "success", "data": {"execution": {"status": "not_attempted", "reason": "no_preselected_backtest_symbols"}}},
        },
        "completed_at": "2026-07-26T19:49:06+00:00",
        "status": "success",
    }


def test_builds_sanitized_alpaca_paper_report_with_phases():
    artifact = build_hourly_operator_artifact(
        preflight=paper_preflight(),
        cycle=cycle(),
        discovery={"response": {"data": {"ranked_candidates": []}}},
        phase_outcomes={"preflight": "success", "portfolio_review": "success", "scanner": "success", "final_reconciliation": "success"},
        workflow={"runId": 123, "conclusion": "unknown"},
    )
    assert artifact["mode"] == "ALPACA_PAPER"
    assert artifact["runtime"]["liveTradingEnabled"] is False
    assert artifact["cycle"]["candidateCount"] == 0
    phase_map = {row["name"]: row["status"] for row in artifact["phases"]}
    assert phase_map["backtest"] == "skipped"
    assert phase_map["risk"] == "skipped"
    assert phase_map["execution"] == "not_attempted"
    assert artifact["response"]["data"]["execution"]["reason"] == "no_preselected_backtest_symbols"


def test_missing_phase_files_still_write_operator_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["build_hourly_operator_artifact.py"])
    assert main() == 0
    payload = json.loads((tmp_path / "reports/hourly-auto-trading-report.json").read_text(encoding="utf-8"))
    assert payload["cycle"]["executionStatus"] == "not_attempted"
    assert payload["warnings"]
    assert payload["runtime"]["liveTradingEnabled"] is False


def test_simulator_mode_remains_fail_closed():
    preflight = paper_preflight()
    preflight["runtime"] = {"paper_automation": False, "broker_mode": "SIMULATOR", "dry_run": True}
    artifact = build_hourly_operator_artifact(preflight=preflight, cycle=cycle())
    assert artifact["mode"] == "SIMULATOR"
    assert artifact["broker_mode"] == "SIMULATOR"
    assert artifact["runtime"]["dryRun"] is True


def test_report_never_copies_raw_order_identifiers():
    payload = cycle()
    payload["review"]["broker_snapshot"] = {
        "orders": {"data": [{"id": "private-id", "client_order_id": "internal-id", "symbol": "ACGL", "qty": "1", "status": "new"}]}
    }
    artifact = build_hourly_operator_artifact(preflight=paper_preflight(), cycle=payload)
    serialized = json.dumps(artifact)
    assert "private-id" not in serialized
    assert "internal-id" not in serialized

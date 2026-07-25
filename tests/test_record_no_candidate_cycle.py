import json
from pathlib import Path

import pytest

from scripts.record_no_candidate_cycle import build_no_candidate_report, main


def test_build_no_candidate_report_is_successful_no_op():
    report = build_no_candidate_report({"market_mode": "SIMULATOR_DRY_RUN"})

    assert report["execute_requested"] is False
    assert report["reason"] == "no_preselected_backtest_symbols"
    assert report["manager_response"]["status"] == "success"
    execution = report["manager_response"]["data"]["execution"]
    assert execution == {
        "status": "not_attempted",
        "reason": "no_preselected_backtest_symbols",
    }


def test_main_writes_manager_cycle_for_ready_preflight(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "hourly-preflight.json").write_text(
        json.dumps(
            {
                "status": "ready",
                "portfolio_cycle_id": "cycle-1",
                "market_mode": "SIMULATOR_DRY_RUN",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    assert main() == 0

    payload = json.loads(
        (reports / "hourly-manager-cycle.json").read_text(encoding="utf-8")
    )
    assert payload["execute_requested"] is False
    assert payload["market_mode"] == "SIMULATOR_DRY_RUN"


def test_main_refuses_unready_preflight(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "hourly-preflight.json").write_text(
        json.dumps({"status": "error", "portfolio_cycle_id": None}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="must be ready"):
        main()

    assert not Path("reports/hourly-manager-cycle.json").exists()

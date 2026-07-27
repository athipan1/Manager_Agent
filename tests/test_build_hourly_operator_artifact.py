import json

from scripts.build_hourly_operator_artifact import (
    build_hourly_operator_artifact,
    main,
)


def _paper_preflight():
    return {
        "status": "ready",
        "portfolio_cycle_id": "hourly-paper-1",
        "market_mode": "PORTFOLIO_REVIEW_ONLY",
        "runtime": {
            "paper_automation": True,
            "broker_mode": "ALPACA",
            "dry_run": False,
        },
    }


def _cycle():
    return {
        "review": {
            "generated_at": "2026-07-26T19:45:30+00:00",
            "portfolio_cycle_id": "hourly-paper-1",
            "protection_diagnostics": {
                "status": "success",
                "summary": {"protected_position_count": 1},
            },
        },
        "candidate_cycle": {
            "execute_requested": False,
            "manager_response": {
                "status": "success",
                "data": {
                    "execution": {
                        "status": "not_attempted",
                        "reason": "no_preselected_backtest_symbols",
                    },
                    "portfolio_summary": {"approved_positions": 0},
                },
            },
        },
        "completed_at": "2026-07-26T19:49:06+00:00",
        "status": "completed",
    }


def _discovery():
    return {
        "response": {
            "status": "success",
            "data": {
                "ranked_candidates": [{"symbol": "BANX"}],
                "exposure_gate": {
                    "summary": {"global_new_entry_blocked": False}
                },
                "portfolio_summary": {
                    "selected_positions": 0,
                    "database_sync_status": "synced",
                },
            },
        }
    }


def test_builds_truthful_alpaca_paper_report_and_merges_discovery():
    artifact = build_hourly_operator_artifact(
        preflight=_paper_preflight(),
        cycle=_cycle(),
        discovery=_discovery(),
    )

    assert artifact["mode"] == "ALPACA_PAPER"
    assert artifact["broker_mode"] == "ALPACA"
    assert artifact["flow"] == "hourly_portfolio_cycle"
    assert artifact["request"]["portfolio_cycle_id"] == "hourly-paper-1"
    assert artifact["response"]["data"]["ranked_candidates"] == [
        {"symbol": "BANX"}
    ]
    assert artifact["response"]["data"]["portfolio_summary"] == {
        "selected_positions": 0,
        "database_sync_status": "synced",
        "approved_positions": 0,
    }
    assert artifact["protection_diagnostics"]["summary"][
        "protected_position_count"
    ] == 1


def test_simulator_mode_remains_fail_closed():
    preflight = _paper_preflight()
    preflight["runtime"] = {
        "paper_automation": False,
        "broker_mode": "SIMULATOR",
        "dry_run": True,
    }

    artifact = build_hourly_operator_artifact(
        preflight=preflight,
        cycle=_cycle(),
    )

    assert artifact["mode"] == "SIMULATOR"
    assert artifact["broker_mode"] == "SIMULATOR"


def test_main_writes_normalized_artifact(tmp_path, monkeypatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "hourly-preflight.json").write_text(
        json.dumps(_paper_preflight()), encoding="utf-8"
    )
    (reports / "hourly-portfolio-cycle.json").write_text(
        json.dumps(_cycle()), encoding="utf-8"
    )
    (reports / "hourly-pre-backtest-discovery.json").write_text(
        json.dumps(_discovery()), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["build_hourly_operator_artifact.py"])

    assert main() == 0
    payload = json.loads(
        (reports / "hourly-auto-trading-report.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["mode"] == "ALPACA_PAPER"
    assert payload["response"]["data"]["ranked_candidates"][0][
        "symbol"
    ] == "BANX"

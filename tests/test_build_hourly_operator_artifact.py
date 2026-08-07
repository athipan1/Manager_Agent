import json

from scripts.build_hourly_operator_artifact import (
    build_hourly_operator_artifact,
    main,
)


def paper_preflight():
    return {
        "status": "ready",
        "portfolio_cycle_id": "hourly-paper-1",
        "market_mode": "PORTFOLIO_REVIEW_ONLY",
        "runtime": {
            "paper_automation": True,
            "broker_mode": "ALPACA",
            "dry_run": False,
            "trading_mode": "PAPER",
        },
        "alpaca_paper": {"account_status": "ACTIVE"},
    }


def cycle():
    return {
        "review": {
            "generated_at": "2026-07-26T19:45:30+00:00",
            "portfolio_cycle_id": "hourly-paper-1",
        },
        "candidate_cycle": {
            "execute_requested": False,
            "manager_response": {
                "status": "success",
                "data": {
                    "execution": {
                        "status": "not_attempted",
                        "reason": "no_preselected_backtest_symbols",
                    }
                },
            },
        },
        "completed_at": "2026-07-26T19:49:06+00:00",
        "status": "success",
    }


def dashboard_state():
    return {
        "generated_at": "2026-07-26T19:48:00+00:00",
        "runtime": {
            "mode": "PAPER",
            "brokerMode": "ALPACA",
            "dryRun": False,
            "liveTradingEnabled": False,
        },
        "account": {
            "cash": "48155.50",
            "equity": "71784.67",
            "buying_power": "275290.36",
            "status": "ACTIVE",
        },
        "positions": [
            {
                "symbol": "ACGL",
                "quantity": "54",
                "avg_entry_price": "104.20",
                "current_price": "104.15",
                "market_value": "5624.10",
                "unrealized_pl": "-2.70",
                "strategy_bucket": "value_rebound",
                "position_id": "private-position-id",
                "protection": {
                    "status": "bracket_protected",
                    "hasStopLoss": True,
                    "hasTakeProfit": True,
                    "hasBracket": True,
                },
            }
        ],
        "orders": [
            {
                "id": "private-order-id",
                "client_order_id": "private-client-order-id",
                "symbol": "ACGL",
                "side": "sell",
                "quantity": "54",
                "order_class": "bracket",
                "type": "limit",
                "status": "new",
                "limit_price": "112.84",
            }
        ],
    }


def test_builds_complete_paper_report_with_real_portfolio_rows():
    artifact = build_hourly_operator_artifact(
        preflight=paper_preflight(),
        cycle=cycle(),
        discovery={"response": {"data": {"ranked_candidates": []}}},
        dashboard_state=dashboard_state(),
        phase_outcomes={
            "preflight": "success",
            "portfolio_review": "success",
            "scanner": "success",
            "final_reconciliation": "success",
        },
        workflow={"runId": 123, "conclusion": "unknown"},
    )
    assert artifact["mode"] == "PAPER"
    assert artifact["broker_mode"] == "ALPACA"
    assert artifact["runtime"]["dryRun"] is False
    assert artifact["runtime"]["liveTradingEnabled"] is False
    assert artifact["account"]["status"] == "ACTIVE"
    assert artifact["positions"][0]["symbol"] == "ACGL"
    assert artifact["openOrders"][0]["symbol"] == "ACGL"
    assert artifact["cycle"]["candidateCount"] == 0
    phase_map = {row["name"]: row["status"] for row in artifact["phases"]}
    assert phase_map["backtest"] == "skipped"
    assert phase_map["risk"] == "not_attempted"
    assert phase_map["execution"] == "not_attempted"
    assert artifact["cycle"]["status"] == "controlled_no_trade"
    assert artifact["cycle"]["brokerOrdersSubmitted"] is False
    serialized = json.dumps(artifact)
    assert "private-position-id" not in serialized
    assert "private-order-id" not in serialized
    assert "private-client-order-id" not in serialized


def test_partial_phase_reports_are_preserved_when_final_cycle_is_missing():
    review = {
        "portfolio_cycle_id": "hourly-paper-1",
        "generated_at": "2026-07-26T19:45:30+00:00",
        "market_mode": "PORTFOLIO_REVIEW_ONLY",
        "position_decisions": [
            {
                "symbol": "ACGL",
                "action": "HOLD",
                "profit_plan": {"primary_action": "hold", "confidence_score": 0.81},
            }
        ],
    }
    manager = {
        "execute_requested": False,
        "market_mode": "PORTFOLIO_REVIEW_ONLY",
        "manager_response": {
            "status": "success",
            "data": {
                "scanner_count": 1,
                "selected_positions": [{"symbol": "ACGL"}],
                "execution": {"status": "not_attempted", "reason": "market_closed"},
            },
        },
    }
    artifact = build_hourly_operator_artifact(
        preflight=paper_preflight(),
        cycle={},
        review=review,
        manager=manager,
        dashboard_state=dashboard_state(),
        phase_outcomes={
            "preflight": "success",
            "portfolio_review": "success",
            "scanner": "success",
            "backtest": "success",
            "final_reconciliation": "skipped",
            "workflow": "success",
        },
    )
    assert artifact["cycle"]["status"] == "partial"
    assert artifact["cycle"]["selectedSymbols"] == ["ACGL"]
    assert artifact["signals"][0]["status"] == "hold"


def test_missing_phase_files_still_write_operator_report(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("sys.argv", ["build_hourly_operator_artifact.py"])
    assert main() == 0
    payload = json.loads(
        (tmp_path / "reports/hourly-auto-trading-report.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["cycle"]["executionStatus"] == "not_attempted"
    assert payload["warnings"]
    assert payload["runtime"]["liveTradingEnabled"] is False


def test_simulator_mode_remains_fail_closed():
    preflight = paper_preflight()
    preflight["runtime"] = {
        "paper_automation": False,
        "broker_mode": "SIMULATOR",
        "dry_run": True,
        "trading_mode": "PAPER",
    }
    artifact = build_hourly_operator_artifact(
        preflight=preflight, cycle=cycle(), dashboard_state={}
    )
    assert artifact["mode"] == "SIMULATOR"
    assert artifact["broker_mode"] == "SIMULATOR"
    assert artifact["runtime"]["dryRun"] is True

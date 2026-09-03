from pathlib import Path

import pytest

from scripts.build_hourly_operator_artifact import build_hourly_operator_artifact
from scripts.resolve_hourly_trade_gate import (
    build_no_trade_report,
    resolve_trade_gate,
)


def preflight(*, market_open: bool, paper_automation: bool = True) -> dict:
    return {
        "status": "ready",
        "portfolio_cycle_id": "hourly-paper-1",
        "market_open": market_open,
        "market_mode": (
            "ALPACA_PAPER_MARKET_OPEN" if market_open else "PORTFOLIO_REVIEW_ONLY"
        ),
        "runtime": {
            "paper_automation": paper_automation,
            "broker_mode": "ALPACA" if paper_automation else "SIMULATOR",
            "dry_run": not paper_automation,
            "trading_mode": "PAPER",
        },
        "alpaca_paper": {"account_status": "ACTIVE"},
    }


def backtest(symbols: list[str]) -> dict:
    return {
        "data": {
            "all_succeeded": True,
            "selection_complete": True,
            "eligible_count": len(symbols),
            "eligible_symbols": symbols,
            "items": [
                {"symbol": symbol, "status": "eligible_strategy_found"}
                for symbol in symbols
            ],
        }
    }


def dashboard() -> dict:
    return {
        "runtime": {
            "mode": "PAPER",
            "brokerMode": "ALPACA",
            "dryRun": False,
            "liveTradingEnabled": False,
        },
        "account": {"status": "ACTIVE"},
        "positions": [],
        "orders": [],
    }


def test_closed_paper_market_is_controlled_no_trade() -> None:
    gate = resolve_trade_gate(preflight(market_open=False), backtest(["MSFT"]))
    assert gate["should_trade"] is False
    assert gate["reason"] == "market_closed"
    assert gate["next_action"] == "WAIT_FOR_REGULAR_SESSION"
    assert gate["eligible_symbols"] == ["MSFT"]
    assert gate["diagnostics"]["market_open"] is False
    assert gate["diagnostics"]["backtest_tested_count"] == 1
    assert gate["diagnostics"]["backtest_eligible_count"] == 1
    assert gate["diagnostics"]["challenger_count"] == 0


def test_open_market_without_eligible_strategy_is_controlled_no_trade() -> None:
    gate = resolve_trade_gate(preflight(market_open=True), backtest([]))
    assert gate["should_trade"] is False
    assert gate["reason"] == "no_eligible_strategy"
    assert gate["next_action"] == "OBSERVE_CHALLENGERS_OR_REVIEW_BACKTEST_REJECTIONS"
    assert gate["diagnostics"]["market_open"] is True
    assert gate["diagnostics"]["backtest_eligible_count"] == 0


def test_open_market_with_eligible_strategy_calls_trade_pipeline() -> None:
    gate = resolve_trade_gate(preflight(market_open=True), backtest(["NVDA"]))
    assert gate["should_trade"] is True
    assert gate["reason"] == "eligible_strategy_available"
    assert gate["next_action"] == "CALL_MANAGER_RISK_EXECUTION"
    assert gate["diagnostics"]["backtest_tested_count"] == 1
    assert gate["diagnostics"]["backtest_eligible_count"] == 1


def test_simulator_can_continue_candidate_analysis_when_market_is_closed() -> None:
    gate = resolve_trade_gate(
        preflight(market_open=False, paper_automation=False), backtest(["MSFT"])
    )
    assert gate["should_trade"] is True


def test_invalid_backtest_count_fails_closed() -> None:
    report = backtest(["MSFT"])
    report["data"]["eligible_count"] = 0
    with pytest.raises(ValueError, match="does not match"):
        resolve_trade_gate(preflight(market_open=True), report)


def test_no_trade_report_persists_trade_gate_diagnostics() -> None:
    ready = preflight(market_open=False)
    report = backtest(["MSFT"])
    gate = resolve_trade_gate(ready, report)
    manager = build_no_trade_report(ready, gate, report)
    assert manager["reason"] == "market_closed"
    assert manager["next_action"] == "WAIT_FOR_REGULAR_SESSION"
    assert manager["trade_gate"]["market_open"] is False
    assert manager["trade_gate"]["backtest_tested_count"] == 1
    assert manager["trade_gate"]["backtest_eligible_count"] == 1
    assert manager["trade_gate"]["eligible_symbols"] == ["MSFT"]
    assert manager["trade_gate"]["challenger_count"] == 0
    assert manager["safety"]["risk_called"] is False
    assert manager["safety"]["execution_called"] is False
    assert manager["safety"]["challenger_lane_broker_mutation_allowed"] is False


def test_operator_artifact_reports_not_attempted_without_false_failure() -> None:
    ready = preflight(market_open=False)
    report = backtest(["MSFT"])
    gate = resolve_trade_gate(ready, report)
    manager = build_no_trade_report(ready, gate, report)
    artifact = build_hourly_operator_artifact(
        preflight=ready,
        cycle={
            "status": "completed",
            "candidate_cycle": manager,
            "completed_at": "2026-08-06T01:00:00+00:00",
        },
        discovery={
            "response": {
                "data": {
                    "scanner_count": 1,
                    "ranked_candidates": [{"symbol": "MSFT"}],
                }
            }
        },
        dashboard_state=dashboard(),
        phase_outcomes={
            "preflight": "success",
            "portfolio_review": "success",
            "protection_reconciliation": "success",
            "scanner": "success",
            "backtest": "success",
            "risk": "skipped",
            "execution": "skipped",
            "final_reconciliation": "success",
            "workflow": "success",
        },
    )
    phases = {item["name"]: item for item in artifact["phases"]}
    assert artifact["cycle"]["status"] == "controlled_no_trade"
    assert artifact["cycle"]["executionStatus"] == "not_attempted"
    assert artifact["cycle"]["executionReason"] == "market_closed"
    assert artifact["cycle"]["brokerOrdersSubmitted"] is False
    assert artifact["broker_orders_submitted"] is False
    assert artifact["error"] is None
    assert phases["risk"]["status"] == "not_attempted"
    assert phases["execution"]["status"] == "not_attempted"
    assert phases["final_reconciliation"]["status"] == "success"


def test_hourly_workflow_guards_trade_and_reconciles_after_portfolio_review() -> None:
    workflow = Path(".github/workflows/hourly-auto-trading.yml").read_text(
        encoding="utf-8"
    )
    assert 'cron: "35 * * * *"' in workflow
    assert 'cron: "5 * * * *"' not in workflow
    assert "steps.trade_gate.outputs.should_trade == 'true'" in workflow
    assert (
        "if: ${{ !cancelled() && steps.portfolio_review.outcome == 'success' }}"
        in workflow
    )
    assert "python scripts/resolve_hourly_trade_gate.py" in workflow

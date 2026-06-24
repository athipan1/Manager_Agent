import json
from pathlib import Path

from scripts.render_hourly_portfolio_report import main


def test_render_hourly_portfolio_report_handles_portfolio_response(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    report = {
        "generated_at": "2026-06-24T14:17:21Z",
        "mode": "ALPACA_PAPER",
        "broker_mode": "ALPACA",
        "flow": "discover_analyze_trade",
        "request": {"account_id": 1, "execute": True},
        "response": {
            "status": "success",
            "data": {
                "mode": "portfolio_allocation",
                "portfolio_summary": {"selected_positions": 2, "approved_positions": 1},
                "allocation_plan": {"policy_name": "core_satellite_50_30_20"},
                "selected_positions": [
                    {"symbol": "KO", "strategy_bucket": "core_dividend", "target_weight": 0.5},
                    {"symbol": "MSFT", "strategy_bucket": "news_momentum", "target_weight": 0.2},
                ],
                "risk_approvals": [
                    {"symbol": "KO", "strategy_bucket": "core_dividend", "approved": True, "final_quantity": 10, "risk_approval_id": "risk-ko"},
                    {"symbol": "MSFT", "strategy_bucket": "news_momentum", "approved": False, "reason": "scaled_quantity_below_minimum"},
                ],
                "execution_candidates": [
                    {"symbol": "KO", "strategy_bucket": "core_dividend", "quantity": 10, "risk_approval_id": "risk-ko", "status": "submitted"}
                ],
                "execution": {"status": "submitted"},
                "ranked_candidates": [],
            },
        },
        "broker_snapshot": {
            "account": {"data": {"status": "ACTIVE", "cash": "1000", "equity": "1000", "buying_power": "4000"}},
            "orders": {"data": []},
            "positions": {"data": []},
        },
        "dashboard_data": {"data": {"summary": {}, "balance": {"cash": "1000"}}},
    }
    (reports_dir / "hourly-auto-trading-report.json").write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert main() == 0

    output = (reports_dir / "hourly-auto-trading-report.md").read_text(encoding="utf-8")
    assert "## Portfolio Summary" in output
    assert "## Selected Positions" in output
    assert "## Risk Approvals" in output
    assert "scaled_quantity_below_minimum" in output
    assert "Winner" not in output

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
                "execution": {
                    "status": "submitted",
                    "validation": {
                        "approved": True,
                        "initial_validation": {
                            "approved": False,
                            "errors": [{"code": "SYMBOL_ALREADY_HAS_OPEN_ORDER", "symbols": ["MSFT"]}],
                        },
                        "skipped_open_order_conflicts": [{"symbol": "MSFT", "reason": "symbol already has an open broker order"}],
                    },
                    "created": [
                        {
                            "symbol": "KO",
                            "strategy_bucket": "core_dividend",
                            "quantity": 10,
                            "final_quantity": 10,
                            "risk_approval_id": "risk-ko",
                            "order_id": 123,
                            "broker_order_id": "broker-123",
                            "status": "PLACED",
                            "execution_job": {"status": "SUCCEEDED"},
                        }
                    ],
                    "skipped_open_order_conflicts": [
                        {"symbol": "MSFT", "quantity": 4, "final_quantity": 4, "risk_approval_id": "risk-msft", "reason": "symbol already has an open broker order"}
                    ],
                    "failed": [],
                    "failed_to_build": [],
                },
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
    assert "## Execution Details" in output
    assert "### Created Orders" in output
    assert "broker-123" in output
    assert "SUCCEEDED" in output
    assert "### Skipped Orders" in output
    assert "symbol already has an open broker order" in output
    assert "### Validation Details" in output
    assert "SYMBOL_ALREADY_HAS_OPEN_ORDER" in output
    assert "Winner" not in output

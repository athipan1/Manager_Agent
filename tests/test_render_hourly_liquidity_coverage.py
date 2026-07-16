import json

from scripts.render_hourly_portfolio_report import main


def test_renderer_rewrites_simulator_warning_and_adds_liquidity_summary(
    tmp_path,
    monkeypatch,
):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    report = {
        "generated_at": "2026-07-16T04:28:00Z",
        "mode": "SIMULATOR",
        "broker_mode": "SIMULATOR",
        "flow": "discover_analyze_trade",
        "warning": (
            "DRY_RUN=false with BROKER_MODE=ALPACA sends orders to Alpaca "
            "Paper only."
        ),
        "request": {"account_id": 1, "execute": True},
        "response": {
            "status": "success",
            "data": {
                "mode": "portfolio_allocation",
                "portfolio_summary": {
                    "selected_positions": 0,
                    "approved_positions": 0,
                },
                "selected_positions": [],
                "risk_approvals": [],
                "execution_candidates": [],
                "execution": {
                    "status": "not_attempted",
                    "reason": "No selected positions passed portfolio selection.",
                },
                "ranked_candidates": [
                    {
                        "symbol": "BANX",
                        "final_verdict": "buy",
                        "strategy_bucket": "value_rebound",
                        "score_breakdown": {
                            "final_opportunity_score": 0.638,
                        },
                        "evidence_summary": {
                            "technical": {
                                "metrics": {
                                    "average_daily_volume": 28_415.0,
                                    "average_dollar_volume": 560_584.645128,
                                },
                                "provenance": {
                                    "liquidity_evidence_version": (
                                        "liquidity-evidence-v1"
                                    ),
                                    "liquidity_evidence_status": "partial",
                                    "liquidity_quote_source": "unavailable",
                                },
                            }
                        },
                        "investability_gate": {
                            "metrics": {
                                "average_dollar_volume": 560_584.645128,
                                "spread_bps": None,
                            }
                        },
                    }
                ],
            },
        },
        "broker_snapshot": {
            "account": {
                "data": {
                    "status": "ACTIVE",
                    "cash": "100000",
                    "equity": "100000",
                    "buying_power": "100000",
                }
            },
            "orders": {"data": []},
            "positions": {"data": []},
        },
        "dashboard_data": {"data": {}},
    }
    report_path = reports_dir / "hourly-auto-trading-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert main() == 0

    enriched = json.loads(report_path.read_text(encoding="utf-8"))
    assert enriched["warning"] == (
        "Simulator safety mode is active; no broker orders will be submitted."
    )
    assert enriched["broker_order_submission_possible"] is False
    assert enriched["liquidity_coverage_summary"][
        "average_dollar_volume_coverage_pct"
    ] == 100.0
    assert enriched["liquidity_coverage_summary"][
        "spread_coverage_pct"
    ] == 0.0

    output = (
        reports_dir / "hourly-auto-trading-report.md"
    ).read_text(encoding="utf-8")
    assert "## Liquidity Evidence Coverage" in output
    assert "Average Dollar Volume: `1/1` (`100.0%`)" in output
    assert "Bid/Ask Spread: `0/1` (`0.0%`)" in output
    assert "Average Dollar Volume Required-Gate Readiness: `eligible`" in output
    assert "Spread Required-Gate Readiness: `not_ready`" in output
    assert '"liquidity-evidence-v1": 1' in output
    assert '"unavailable": 1' in output

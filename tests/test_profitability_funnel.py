from scripts.build_profitability_funnel import build_profitability_funnel, render_markdown


def _report():
    return {
        "status": "success",
        "request": {"max_universe": 1000},
        "backtest_symbols": [],
        "response": {
            "status": "success",
            "data": {
                "report_id": "hourly-paper-test",
                "scanner_metadata": {
                    "attempted_count": 1000,
                    "analyzed_count": 318,
                    "provider_pressure_detected": True,
                    "error_categories": {
                        "missing_financial_statements": 657,
                        "provider_rate_limited": 23,
                    },
                    "scanner_data_quality_gate": {
                        "passed_count": 8,
                        "decision": "PARTIAL",
                        "review_reason_codes": [
                            "SCANNER_DATA_COVERAGE_BELOW_THRESHOLD"
                        ],
                    },
                },
                "scanner_count": 8,
                "deep_analysis_count": 8,
                "ranked_candidates": [
                    {
                        "symbol": "BANX",
                        "strategy_bucket": "value_rebound",
                        "evidence_gate_passed": True,
                    },
                    {
                        "symbol": "META",
                        "strategy_bucket": "unassigned",
                        "evidence_gate_passed": True,
                    },
                ],
                "bucket_selection": {
                    "summary": {
                        "quarantine_count": 1,
                        "selected_before_investability": 1,
                        "selected_after_investability": 0,
                    }
                },
                "allocation_plan": {
                    "investability_gate": {
                        "rejected": [
                            {
                                "symbol": "BANX",
                                "rejection_codes": [
                                    "investability_market_cap_below_minimum",
                                    "investability_average_dollar_volume_below_minimum",
                                ],
                            }
                        ]
                    }
                },
                "exposure_gate": {
                    "summary": {
                        "allowed_count": 0,
                    }
                },
                "pre_backtest_selected_positions": [],
            },
        },
    }


def test_builds_diagnostic_funnel_without_relaxing_safety():
    funnel = build_profitability_funnel(_report())

    assert funnel["schema_version"] == "profitability-funnel.v1"
    assert funnel["health"]["scanner_success_rate"] == 0.318
    assert funnel["health"]["scanner_provider_pressure_detected"] is True
    assert funnel["health"]["quarantine_count"] == 1
    assert funnel["health"]["investability_rejection_codes"] == {
        "investability_average_dollar_volume_below_minimum": 1,
        "investability_market_cap_below_minimum": 1,
    }
    assert funnel["primary_bottleneck"]["stage"] == "scanner_provider_coverage"
    assert {row["stage"] for row in funnel["active_bottlenecks"]} >= {
        "scanner_provider_coverage",
        "investability_gate",
        "backtest_handoff",
    }
    assert funnel["safety"] == {
        "risk_thresholds_relaxed": False,
        "investability_thresholds_relaxed": False,
        "purpose": "diagnostic_only",
    }


def test_reports_healthy_handoff_when_one_symbol_reaches_backtest():
    report = _report()
    report["response"]["data"]["scanner_metadata"]["attempted_count"] = 100
    report["response"]["data"]["scanner_metadata"]["analyzed_count"] = 95
    report["response"]["data"]["bucket_selection"]["summary"][
        "selected_after_investability"
    ] = 1
    report["response"]["data"]["allocation_plan"]["investability_gate"][
        "rejected"
    ] = []
    report["response"]["data"]["exposure_gate"]["summary"]["allowed_count"] = 1
    report["response"]["data"]["pre_backtest_selected_positions"] = [
        {"symbol": "AAPL"}
    ]
    report["backtest_symbols"] = ["AAPL"]

    funnel = build_profitability_funnel(report)

    assert funnel["health"]["scanner_success_rate"] == 0.95
    assert funnel["health"]["backtest_symbols"] == ["AAPL"]
    assert all(
        issue["stage"] not in {"scanner_provider_coverage", "backtest_handoff"}
        for issue in funnel["active_bottlenecks"]
    )


def test_markdown_surfaces_primary_operational_metrics():
    markdown = render_markdown(build_profitability_funnel(_report()))

    assert "Hourly Profitability Funnel Audit" in markdown
    assert "Scanner success rate: `31.8%`" in markdown
    assert "**scanner_provider_coverage**" in markdown
    assert "does not relax Risk or Investability thresholds" in markdown

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
                        "original_count": 10,
                        "passed_count": 8,
                        "review_count": 2,
                        "decision": "PARTIAL",
                        "min_coverage_ratio": 0.80,
                        "threshold_relaxed": False,
                        "coverage_scope_counts": {"analysis_ready": 10},
                        "review_reason_codes": [
                            "SCANNER_DATA_COVERAGE_BELOW_THRESHOLD"
                        ],
                        "evaluations": [
                            {
                                "symbol": "GAP1",
                                "allowed": False,
                                "reason_code": "SCANNER_DATA_COVERAGE_BELOW_THRESHOLD",
                            },
                            {
                                "symbol": "GAP2",
                                "allowed": False,
                                "reason_code": "SCANNER_DATA_COVERAGE_BELOW_THRESHOLD",
                            },
                        ],
                    },
                    "scanner_opportunity_gate": {
                        "original_count": 8,
                        "passed_count": 3,
                        "review_count": 5,
                        "decision": "PARTIAL",
                        "review_reason_codes": ["SCANNER_OPPORTUNITY_MARKET_CLOSED"],
                        "evaluations": [
                            {
                                "symbol": "R1",
                                "allowed": False,
                                "reason_code": "SCANNER_OPPORTUNITY_MARKET_CLOSED",
                            },
                            {
                                "symbol": "R2",
                                "allowed": False,
                                "reason_code": "SCANNER_OPPORTUNITY_MARKET_CLOSED",
                            },
                        ],
                    },
                },
                "scanner_count": 3,
                "research_candidate_count": 5,
                "research_candidates": [{"symbol": "R1"}, {"symbol": "R2"}],
                "deep_analysis_count": 3,
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

    assert funnel["schema_version"] == "profitability-funnel.v2"
    assert funnel["health"]["scanner_success_rate"] == 0.318
    assert funnel["health"]["scanner_provider_pressure_detected"] is True
    assert funnel["health"]["production_candidate_count"] == 3
    assert funnel["health"]["research_candidate_count"] == 5
    assert funnel["health"]["data_quality_threshold"] == 0.80
    assert funnel["health"]["data_quality_threshold_relaxed"] is False
    assert funnel["health"]["data_quality_coverage_scope_counts"] == {
        "analysis_ready": 10
    }
    assert funnel["health"]["data_quality_rejection_reasons"] == {
        "SCANNER_DATA_COVERAGE_BELOW_THRESHOLD": 2
    }
    assert funnel["health"]["opportunity_rejection_reasons"] == {
        "SCANNER_OPPORTUNITY_MARKET_CLOSED": 2
    }
    assert funnel["health"]["quarantine_count"] == 1
    assert funnel["health"]["investability_rejection_codes"] == {
        "investability_average_dollar_volume_below_minimum": 1,
        "investability_market_cap_below_minimum": 1,
    }
    assert funnel["primary_bottleneck"]["stage"] == "scanner_provider_coverage"
    assert {row["stage"] for row in funnel["active_bottlenecks"]} >= {
        "scanner_provider_coverage",
        "scanner_analysis_data_quality_gate",
        "scanner_production_opportunity_gate",
        "investability_gate",
        "backtest_handoff",
    }
    assert funnel["safety"] == {
        "scanner_data_quality_threshold_relaxed": False,
        "production_opportunity_threshold_relaxed": False,
        "risk_thresholds_relaxed": False,
        "investability_thresholds_relaxed": False,
        "shadow_broker_order_authorized": False,
        "purpose": "diagnostic_only",
    }


def test_funnel_separates_analysis_production_and_shadow_counts():
    funnel = build_profitability_funnel(_report())
    stages = {row["name"]: row for row in funnel["stages"]}

    assert stages["scanner_gate_input"]["count"] == 10
    assert stages["scanner_analysis_ready"]["count"] == 8
    assert stages["scanner_production_ready"]["count"] == 3
    assert stages["scanner_research_shadow"]["count"] == 5
    assert stages["scanner_research_shadow"]["execution_authorized"] is False


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
    assert "Production candidates: `3`" in markdown
    assert "Shadow research candidates: `5`" in markdown
    assert "Data quality threshold relaxed: `False`" in markdown
    assert "**scanner_provider_coverage**" in markdown
    assert "never authorizes Shadow broker orders" in markdown

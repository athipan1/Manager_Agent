from app import discover_report_builder as builder


def _ranked(symbol, *, price, market_cap, atr_percent, regime="normal"):
    evidence = {
        "raw_scores": {
            "scanner": {"market_cap": market_cap},
            "technical": {
                "current_price": price,
                "atr_percent": atr_percent,
                "volatility_regime": regime,
            },
        },
        "evidence_versions": {},
        "evidence_statuses": {},
        "source_conflicts": [],
    }
    return {
        "symbol": symbol,
        "strategy_bucket": "value_rebound",
        "bucket_confidence": 0.9,
        "bucket_classification_status": "classified",
        "bucket_classification_reasons": [],
        "bucket_classifier_version": "test-v1",
        "strategy_bucket_classification": {},
        "evidence_gate_passed": True,
        "evidence_summary": evidence,
        "analysis": {
            "ticker": symbol,
            "final_verdict": "buy",
            "status": "complete",
            "evidence_summary": evidence,
        },
        "score_breakdown": {
            "strategy_bucket": "value_rebound",
            "final_opportunity_score": 0.9,
        },
        "scanner_candidate": {"symbol": symbol},
    }


def test_allocation_report_filters_microcap_before_pre_backtest(monkeypatch):
    ranked = [
        _ranked(
            "MBAI",
            price=1.01,
            market_cap=7_846_314.0,
            atr_percent=11.3457,
            regime="extreme",
        ),
        _ranked(
            "AAPL",
            price=190.0,
            market_cap=3_000_000_000_000.0,
            atr_percent=2.5,
        ),
    ]
    bucket_selection = {
        "value_rebound": {
            "selected": [
                {"symbol": "MBAI", "capacity_adjusted_target_value": 500.0},
                {"symbol": "AAPL", "capacity_adjusted_target_value": 500.0},
            ],
            "selected_count": 2,
        },
        "summary": {},
    }
    allocation_plan = {
        "policy_name": "test-policy",
        "buckets": {
            "value_rebound": {
                "target_weight": 0.3,
                "target_value": 3_000.0,
                "max_symbol_value": 1_000.0,
                "candidates": [
                    {"symbol": "MBAI", "suggested_max_value": 500.0},
                    {"symbol": "AAPL", "suggested_max_value": 500.0},
                ],
            }
        },
    }

    monkeypatch.setattr(
        builder,
        "enrich_ranked_candidates_with_buckets",
        lambda rows: rows,
    )
    monkeypatch.setattr(
        builder,
        "build_discover_allocation_plan",
        lambda rows, portfolio_value: allocation_plan,
    )
    monkeypatch.setattr(
        builder,
        "select_candidates_by_bucket",
        lambda rows, min_final_score: bucket_selection,
    )
    monkeypatch.setattr(
        builder,
        "apply_pre_risk_capacity_selection",
        lambda **kwargs: {
            "bucket_selection": bucket_selection,
            "skipped": [],
            "promoted": [],
        },
    )
    monkeypatch.setattr(
        builder,
        "ranked_response_rows",
        lambda rows: [dict(row) for row in rows],
    )
    monkeypatch.setattr(builder.config, "INVESTABILITY_GATE_ENABLED", True)
    monkeypatch.setattr(builder.config, "INVESTABILITY_MIN_PRICE_USD", 3.0)
    monkeypatch.setattr(
        builder.config,
        "INVESTABILITY_MIN_MARKET_CAP_USD",
        300_000_000.0,
    )
    monkeypatch.setattr(
        builder.config,
        "INVESTABILITY_MIN_AVG_DOLLAR_VOLUME_USD",
        5_000_000.0,
    )
    monkeypatch.setattr(builder.config, "INVESTABILITY_MAX_SPREAD_BPS", 100.0)
    monkeypatch.setattr(builder.config, "INVESTABILITY_MAX_ATR_PCT", 15.0)
    monkeypatch.setattr(
        builder.config,
        "INVESTABILITY_REQUIRE_AVG_DOLLAR_VOLUME",
        False,
    )
    monkeypatch.setattr(builder.config, "INVESTABILITY_REQUIRE_SPREAD", False)
    monkeypatch.setattr(builder.config, "INVESTABILITY_REQUIRE_ATR", True)
    monkeypatch.setattr(
        builder.config,
        "INVESTABILITY_BLOCK_EXTREME_VOLATILITY",
        True,
    )

    report = builder.build_discover_allocation_report(
        ranked=ranked,
        portfolio_value=10_000.0,
        min_final_score=0.55,
        positions=[],
    )

    assert [row["symbol"] for row in report["selected_positions"]] == ["AAPL"]
    assert [row["ticker"] for row in report["position_analysis_payloads"]] == [
        "AAPL"
    ]
    assert report["winner"]["symbol"] == "AAPL"
    gate = report["allocation_plan"]["investability_gate"]
    assert gate["summary"]["blocked_count"] == 1
    assert gate["rejected"][0]["symbol"] == "MBAI"
    assert report["bucket_selection"]["summary"][
        "selected_before_investability"
    ] == 2
    assert report["bucket_selection"]["summary"][
        "selected_after_investability"
    ] == 1
    assert report["ranked_candidates"][0]["investability_gate"][
        "status"
    ] == "block"

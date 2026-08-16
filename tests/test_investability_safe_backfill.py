from app import discover_report_builder as builder


def _ranked(symbol, *, market_cap, score=0.90, bucket="value_rebound"):
    evidence = {
        "raw_scores": {
            "scanner": {"market_cap": market_cap},
            "technical": {
                "current_price": 100.0,
                "atr_percent": 2.5,
                "average_dollar_volume": 20_000_000.0,
            },
        },
        "evidence_versions": {},
        "evidence_statuses": {},
        "source_conflicts": [],
    }
    return {
        "symbol": symbol,
        "strategy_bucket": bucket,
        "bucket_confidence": 0.95,
        "bucket_classification_status": "classified",
        "bucket_classification_reasons": [],
        "bucket_classifier_version": "test-v1",
        "strategy_bucket_classification": {},
        "evidence_gate_passed": True,
        "evidence_summary": evidence,
        "analysis": {
            "ticker": symbol,
            "current_price": 100.0,
            "market_cap": market_cap,
            "atr_percent": 2.5,
            "average_dollar_volume": 20_000_000.0,
            "final_verdict": "buy",
            "status": "complete",
            "evidence_summary": evidence,
        },
        "score_breakdown": {
            "strategy_bucket": bucket,
            "final_opportunity_score": score,
        },
        "scanner_candidate": {"symbol": symbol, "market_cap": market_cap},
    }


def _allocation_plan(rows, bucket="value_rebound"):
    return {
        "policy_name": "test-policy",
        "buckets": {
            bucket: {
                "target_weight": 0.3,
                "target_value": 3_000.0,
                "max_symbol_value": 700.0,
                "candidates": [
                    {
                        "symbol": row["symbol"],
                        "suggested_equal_weight_value": 500.0,
                        "suggested_max_value": 700.0,
                    }
                    for row in rows
                    if row["strategy_bucket"] == bucket
                ],
            }
        },
    }


def _bucket_selection(selected, overflow, *, bucket="value_rebound", limit=1):
    return {
        bucket: {
            "limit": limit,
            "eligible_count": len(selected) + len(overflow),
            "selected_count": len(selected),
            "selected": [
                {
                    "symbol": row["symbol"],
                    "strategy_bucket": bucket,
                    "bucket_classification_status": "classified",
                    "bucket_confidence": 0.95,
                    "evidence_gate_passed": True,
                    "final_verdict": "buy",
                    "score_breakdown": row["score_breakdown"],
                }
                for row in selected
            ],
            "overflow": [
                {
                    "symbol": row["symbol"],
                    "strategy_bucket": bucket,
                    "bucket_classification_status": "classified",
                    "bucket_confidence": 0.95,
                    "evidence_gate_passed": True,
                    "final_verdict": "buy",
                    "score_breakdown": row["score_breakdown"],
                }
                for row in overflow
            ],
        },
        "summary": {
            "total_selected": len(selected),
            "limits": {bucket: limit},
            "min_final_score": 0.55,
        },
    }


def _configure_gate(monkeypatch):
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


def _install_selection(monkeypatch, ranked, selected, overflow):
    plan = _allocation_plan(ranked)
    selection = _bucket_selection(selected, overflow)
    monkeypatch.setattr(
        builder,
        "enrich_ranked_candidates_with_buckets",
        lambda rows: rows,
    )
    monkeypatch.setattr(
        builder,
        "build_discover_allocation_plan",
        lambda rows, portfolio_value: plan,
    )
    monkeypatch.setattr(
        builder,
        "select_candidates_by_bucket",
        lambda rows, min_final_score: selection,
    )
    monkeypatch.setattr(
        builder,
        "ranked_response_rows",
        lambda rows: [dict(row) for row in rows],
    )
    return plan, selection


def test_rejected_primary_promotes_same_bucket_investable_backup(monkeypatch):
    bad = _ranked("BAD", market_cap=100_000_000.0, score=0.95)
    good = _ranked("GOOD", market_cap=10_000_000_000.0, score=0.90)
    ranked = [bad, good]
    _configure_gate(monkeypatch)
    _install_selection(monkeypatch, ranked, [bad], [good])

    report = builder.build_discover_allocation_report(
        ranked=ranked,
        portfolio_value=10_000.0,
        min_final_score=0.55,
        positions=[],
    )

    assert [row["symbol"] for row in report["selected_positions"]] == ["GOOD"]
    assert report["selected_positions"][0]["investability_fallback_promoted"] is True
    assert report["selected_positions"][0]["capacity_adjusted_target_value"] <= 700.0
    assert report["investability_gate"]["rejected"][0]["symbol"] == "BAD"
    assert report["investability_gate"]["fallback_promoted_symbols"] == ["GOOD"]
    assert report["investability_fallback"]["retry_pool_expanded"] is False
    assert report["investability_fallback"]["thresholds_relaxed"] is False
    assert report["bucket_selection"]["summary"][
        "investability_fallback_promoted_count"
    ] == 1


def test_rejected_backup_is_never_forwarded(monkeypatch):
    bad = _ranked("BAD", market_cap=100_000_000.0, score=0.95)
    bad2 = _ranked("BAD2", market_cap=200_000_000.0, score=0.90)
    ranked = [bad, bad2]
    _configure_gate(monkeypatch)
    _install_selection(monkeypatch, ranked, [bad], [bad2])

    report = builder.build_discover_allocation_report(
        ranked=ranked,
        portfolio_value=10_000.0,
        min_final_score=0.55,
        positions=[],
    )

    assert report["selected_positions"] == []
    assert {row["symbol"] for row in report["investability_gate"]["rejected"]} == {
        "BAD",
        "BAD2",
    }
    assert report["investability_gate"]["fallback_promoted_count"] == 0
    assert report["bucket_selection"]["summary"]["selected_after_investability"] == 0


def test_backfill_does_not_cross_bucket_limits(monkeypatch):
    bad = _ranked("BAD", market_cap=100_000_000.0, score=0.95)
    other = _ranked(
        "OTHER",
        market_cap=10_000_000_000.0,
        score=0.90,
        bucket="core_dividend",
    )
    ranked = [bad, other]
    _configure_gate(monkeypatch)
    plan = {
        "policy_name": "test-policy",
        "buckets": {
            "value_rebound": {
                "target_weight": 0.3,
                "target_value": 3_000.0,
                "max_symbol_value": 700.0,
                "candidates": [
                    {
                        "symbol": "BAD",
                        "suggested_equal_weight_value": 500.0,
                        "suggested_max_value": 700.0,
                    }
                ],
            },
            "core_dividend": {
                "target_weight": 0.5,
                "target_value": 5_000.0,
                "max_symbol_value": 1_000.0,
                "candidates": [
                    {
                        "symbol": "OTHER",
                        "suggested_equal_weight_value": 500.0,
                        "suggested_max_value": 1_000.0,
                    }
                ],
            },
        },
    }
    selection = {
        "value_rebound": {
            "limit": 1,
            "eligible_count": 1,
            "selected_count": 1,
            "selected": [
                {
                    "symbol": "BAD",
                    "strategy_bucket": "value_rebound",
                    "bucket_classification_status": "classified",
                    "bucket_confidence": 0.95,
                    "evidence_gate_passed": True,
                    "final_verdict": "buy",
                    "score_breakdown": bad["score_breakdown"],
                }
            ],
            "overflow": [],
        },
        "core_dividend": {
            "limit": 0,
            "eligible_count": 1,
            "selected_count": 0,
            "selected": [],
            "overflow": [
                {
                    "symbol": "OTHER",
                    "strategy_bucket": "core_dividend",
                    "bucket_classification_status": "classified",
                    "bucket_confidence": 0.95,
                    "evidence_gate_passed": True,
                    "final_verdict": "buy",
                    "score_breakdown": other["score_breakdown"],
                }
            ],
        },
        "summary": {"limits": {"value_rebound": 1, "core_dividend": 0}},
    }
    monkeypatch.setattr(builder, "enrich_ranked_candidates_with_buckets", lambda rows: rows)
    monkeypatch.setattr(
        builder,
        "build_discover_allocation_plan",
        lambda rows, portfolio_value: plan,
    )
    monkeypatch.setattr(
        builder,
        "select_candidates_by_bucket",
        lambda rows, min_final_score: selection,
    )
    monkeypatch.setattr(builder, "ranked_response_rows", lambda rows: [dict(row) for row in rows])

    report = builder.build_discover_allocation_report(
        ranked=ranked,
        portfolio_value=10_000.0,
        min_final_score=0.55,
        positions=[],
    )

    assert report["selected_positions"] == []
    assert report["investability_fallback"]["promoted_symbols"] == []


def test_unchanged_investability_thresholds_are_recorded_for_fallback(monkeypatch):
    bad = _ranked("BAD", market_cap=100_000_000.0, score=0.95)
    good = _ranked("GOOD", market_cap=10_000_000_000.0, score=0.90)
    ranked = [bad, good]
    _configure_gate(monkeypatch)
    _install_selection(monkeypatch, ranked, [bad], [good])

    report = builder.build_discover_allocation_report(
        ranked=ranked,
        portfolio_value=10_000.0,
        min_final_score=0.55,
        positions=[],
    )

    decisions = {
        row["symbol"]: row for row in report["investability_gate"]["decisions"]
    }
    assert decisions["BAD"]["thresholds"] == decisions["GOOD"]["thresholds"]
    assert decisions["GOOD"]["thresholds"]["min_market_cap_usd"] == 300_000_000.0

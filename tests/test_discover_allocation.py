from decimal import Decimal

from app.discover_allocation import (
    build_discover_allocation_plan,
    choose_bucket_aware_winner,
    enrich_ranked_candidates_with_buckets,
    ranked_response_rows,
    select_candidates_by_bucket,
)
from app.discover_report_builder import (
    build_discover_allocation_report,
    build_position_analysis_payloads,
    build_selected_positions,
)


def _item(
    symbol,
    score,
    verdict="buy",
    tags=None,
    raw_scores=None,
    bucket_hint=None,
):
    metadata = {"tags": tags or []}
    if bucket_hint:
        metadata["primary_strategy_bucket_hint"] = bucket_hint
        metadata["strategy_bucket_hints"] = [bucket_hint]
        metadata["bucket_hint_scores"] = {bucket_hint: 0.9}
    return {
        "symbol": symbol,
        "analysis": {
            "ticker": symbol,
            "final_verdict": verdict,
            "status": "complete",
            "details": {},
        },
        "scanner_candidate": {
            "metadata": metadata,
            "raw_scores": raw_scores or {},
        },
        "score_breakdown": {"final_opportunity_score": score},
    }


def test_enrich_ranked_candidates_adds_strategy_bucket_and_classifier_metadata():
    ranked = [
        _item("KO", 0.66, tags=["dividend"]),
        _item("NEWS", 0.70, tags=["news"]),
    ]

    enriched = enrich_ranked_candidates_with_buckets(ranked)

    assert enriched[0]["strategy_bucket"] == "core_dividend"
    assert (
        enriched[0]["score_breakdown"]["strategy_bucket"]
        == "core_dividend"
    )
    assert enriched[0]["bucket_confidence"] >= 0.70
    assert enriched[0]["bucket_classification_status"] == "classified"
    assert (
        enriched[0]["bucket_classifier_version"]
        == "manager-strategy-bucket-v3"
    )
    assert enriched[1]["strategy_bucket"] == "news_momentum"


def test_scanner_primary_bucket_hint_is_used_when_not_conflicting():
    ranked = [_item("SCANNER", 0.66, bucket_hint="news_momentum")]

    enriched = enrich_ranked_candidates_with_buckets(ranked)

    assert enriched[0]["strategy_bucket"] == "news_momentum"
    assert enriched[0]["bucket_confidence"] == 0.9
    assert enriched[0]["bucket_classification_status"] == "classified"


def test_scanner_hint_conflicting_with_strong_heuristics_is_quarantined():
    ranked = [
        _item(
            "CONFLICT",
            0.66,
            tags=["dividend", "quality"],
            raw_scores={"pe_ratio": 10},
            bucket_hint="news_momentum",
        ),
    ]

    enriched = enrich_ranked_candidates_with_buckets(ranked)

    assert enriched[0]["strategy_bucket"] == "unassigned"
    assert enriched[0]["bucket_classification_status"] == "conflict"
    assert (
        enriched[0]["strategy_bucket_classification"][
            "allows_new_entry"
        ]
        is False
    )


def test_build_discover_allocation_plan_contains_50_30_20_buckets():
    ranked = [
        _item("KO", 0.66, tags=["dividend"]),
        _item("ACGL", 0.61, raw_scores={"pe_ratio": 12}),
        _item("NEWS", 0.70, tags=["news"]),
    ]

    plan = build_discover_allocation_plan(ranked, Decimal("100000"))

    assert plan["policy_name"] == "core_satellite_50_30_20"
    assert plan["buckets"]["core_dividend"]["target_value"] == 50000.0
    assert plan["buckets"]["value_rebound"]["target_value"] == 30000.0
    assert plan["buckets"]["news_momentum"]["target_value"] == 20000.0
    assert plan["quarantine_count"] == 0


def test_choose_bucket_aware_winner_prefers_core_when_eligible():
    ranked = [
        _item("NEWS", 0.90, tags=["news"]),
        _item("KO", 0.66, tags=["dividend"]),
        _item("ACGL", 0.80, raw_scores={"pe_ratio": 12}),
    ]
    plan = build_discover_allocation_plan(ranked, Decimal("100000"))

    winner = choose_bucket_aware_winner(
        ranked,
        plan,
        min_final_score=0.55,
    )

    assert winner["symbol"] == "KO"
    assert winner["strategy_bucket"] == "core_dividend"


def test_choose_bucket_aware_winner_uses_scanner_hint_bucket_priority():
    ranked = [
        _item("NEWS", 0.90, bucket_hint="news_momentum"),
        _item("CORE", 0.66, bucket_hint="core_dividend"),
        _item("VALUE", 0.80, bucket_hint="value_rebound"),
    ]
    plan = build_discover_allocation_plan(ranked, Decimal("100000"))

    winner = choose_bucket_aware_winner(
        ranked,
        plan,
        min_final_score=0.55,
    )

    assert winner["symbol"] == "CORE"
    assert winner["strategy_bucket"] == "core_dividend"


def test_choose_bucket_aware_winner_falls_back_to_best_classified_eligible():
    ranked = [
        _item("NEWS", 0.90, tags=["news"]),
        _item("ACGL", 0.80, raw_scores={"pe_ratio": 12}),
    ]
    plan = build_discover_allocation_plan(ranked, Decimal("100000"))

    winner = choose_bucket_aware_winner(
        ranked,
        plan,
        min_final_score=0.55,
    )

    assert winner["symbol"] == "ACGL"
    assert winner["strategy_bucket"] == "value_rebound"


def test_choose_bucket_aware_winner_returns_empty_when_all_candidates_are_unassigned():
    ranked = [_item("UNKNOWN", 0.99)]
    plan = build_discover_allocation_plan(ranked, Decimal("100000"))

    winner = choose_bucket_aware_winner(
        ranked,
        plan,
        min_final_score=0.55,
    )

    assert winner == {}


def test_ranked_response_rows_include_strategy_bucket_and_gate_fields():
    ranked = [_item("NEWS", 0.70, tags=["news"])]

    rows = ranked_response_rows(ranked)

    assert rows[0]["strategy_bucket"] == "news_momentum"
    assert (
        rows[0]["score_breakdown"]["strategy_bucket"]
        == "news_momentum"
    )
    assert rows[0]["bucket_classification_status"] == "classified"
    assert rows[0]["allows_new_entry"] is True
    assert rows[0]["evidence_gate_passed"] is True


def test_select_candidates_by_bucket_uses_default_limits():
    ranked = [
        _item("KO", 0.80, tags=["dividend"]),
        _item("JNJ", 0.75, tags=["dividend"]),
        _item("PEP", 0.70, tags=["dividend"]),
        _item("ACGL", 0.82, raw_scores={"pe_ratio": 12}),
        _item("ADBE", 0.78, raw_scores={"pe_ratio": 14}),
        _item("AMZN", 0.76, raw_scores={"pe_ratio": 16}),
        _item("NEWS1", 0.90, tags=["news"]),
        _item("NEWS2", 0.88, tags=["news"]),
    ]

    selection = select_candidates_by_bucket(
        ranked,
        min_final_score=0.55,
    )

    assert selection["core_dividend"]["selected_count"] == 2
    assert [
        row["symbol"]
        for row in selection["core_dividend"]["selected"]
    ] == ["KO", "JNJ"]
    assert selection["value_rebound"]["selected_count"] == 2
    assert [
        row["symbol"]
        for row in selection["value_rebound"]["selected"]
    ] == ["ACGL", "ADBE"]
    assert selection["news_momentum"]["selected_count"] == 1
    assert [
        row["symbol"]
        for row in selection["news_momentum"]["selected"]
    ] == ["NEWS1"]
    assert selection["summary"]["total_selected"] == 5
    assert selection["summary"]["quarantine_count"] == 1
    assert selection["summary"]["quarantined_symbols"] == ["AMZN"]


def test_select_candidates_by_bucket_blocks_high_score_unclassified_buy():
    ranked = [_item("UNKNOWN", 0.99, verdict="strong_buy")]

    selection = select_candidates_by_bucket(
        ranked,
        min_final_score=0.55,
    )

    assert selection["summary"]["total_selected"] == 0
    assert selection["summary"]["quarantine_count"] == 1
    assert selection["summary"]["quarantined_symbols"] == ["UNKNOWN"]


def test_build_selected_positions_exports_classifier_contract():
    ranked = [
        _item("KO", 0.80, tags=["dividend"]),
        _item("ACGL", 0.82, raw_scores={"pe_ratio": 12}),
        _item("NEWS1", 0.90, tags=["news"]),
    ]
    enriched = enrich_ranked_candidates_with_buckets(ranked)
    plan = build_discover_allocation_plan(enriched, Decimal("100000"))
    selection = select_candidates_by_bucket(
        enriched,
        min_final_score=0.55,
    )

    selected_positions = build_selected_positions(
        ranked=enriched,
        allocation_plan=plan,
        bucket_selection=selection,
    )

    assert [
        position["symbol"] for position in selected_positions
    ] == ["KO", "ACGL", "NEWS1"]
    assert selected_positions[0]["strategy_bucket"] == "core_dividend"
    assert selected_positions[0]["target_weight"] == 0.5
    assert selected_positions[0]["allocation_pct"] == 50.0
    assert selected_positions[0]["bucket_confidence"] >= 0.70
    assert (
        selected_positions[0]["bucket_classification_status"]
        == "classified"
    )
    assert selected_positions[0]["evidence_gate_passed"] is True
    assert selected_positions[1]["strategy_bucket"] == "value_rebound"
    assert selected_positions[2]["strategy_bucket"] == "news_momentum"


def test_position_analysis_payloads_include_allocation_and_classifier_context():
    ranked = enrich_ranked_candidates_with_buckets(
        [
            _item("KO", 0.80, tags=["dividend"]),
            _item("ACGL", 0.82, raw_scores={"pe_ratio": 12}),
        ]
    )
    plan = build_discover_allocation_plan(ranked, Decimal("100000"))
    selection = select_candidates_by_bucket(
        ranked,
        min_final_score=0.55,
    )
    selected_positions = build_selected_positions(
        ranked=ranked,
        allocation_plan=plan,
        bucket_selection=selection,
    )

    payloads = build_position_analysis_payloads(
        ranked=ranked,
        selected_positions=selected_positions,
    )

    assert [payload["ticker"] for payload in payloads] == ["KO", "ACGL"]
    assert payloads[0]["strategy_bucket"] == "core_dividend"
    assert payloads[0]["portfolio_context"]["target_weight"] == 0.5
    assert payloads[0]["portfolio_context"]["allocation_pct"] == 50.0
    assert (
        payloads[0]["portfolio_context"]["bucket_confidence"]
        >= 0.70
    )
    assert (
        payloads[0]["bucket_classifier_version"]
        == "manager-strategy-bucket-v3"
    )
    assert payloads[0]["evidence_gate_passed"] is True
    assert payloads[1]["strategy_bucket"] == "value_rebound"


def test_build_discover_allocation_report_includes_classification_gate():
    ranked = [
        _item("KO", 0.80, tags=["dividend"]),
        _item("ACGL", 0.82, raw_scores={"pe_ratio": 12}),
        _item("NEWS1", 0.90, tags=["news"]),
        _item("UNKNOWN", 0.99),
    ]

    report = build_discover_allocation_report(
        ranked=ranked,
        portfolio_value=Decimal("100000"),
        min_final_score=0.55,
    )

    assert "bucket_selection" in report
    assert "selected_positions" in report
    assert "position_analysis_payloads" in report
    assert "classification_gate" in report
    assert report["bucket_selection"]["summary"]["total_selected"] == 3
    assert report["classification_gate"]["approved_count"] == 3
    assert report["classification_gate"]["quarantine_count"] == 1
    assert report["classification_gate"]["quarantined_symbols"] == [
        "UNKNOWN"
    ]
    assert [
        position["symbol"] for position in report["selected_positions"]
    ] == ["KO", "ACGL", "NEWS1"]
    assert [
        payload["ticker"]
        for payload in report["position_analysis_payloads"]
    ] == ["KO", "ACGL", "NEWS1"]

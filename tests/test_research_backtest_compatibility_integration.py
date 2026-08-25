from app.services import research_backtest_selection_service as selection_service


def _row(symbol: str, *, bucket: str, final_score: float):
    return {
        "symbol": symbol,
        "strategy_bucket": bucket,
        "bucket_confidence": 0.90,
        "bucket_classification_status": "classified",
        "evidence_gate_passed": True,
        "final_verdict": "hold",
        "score_breakdown": {"final_opportunity_score": final_score},
        "scanner_candidate": {"metadata": {"details": {"data_bundle": {}}}},
    }


def test_known_single_strategy_intersection_is_excluded_before_slot_selection(monkeypatch):
    rows = [
        _row("VALUE", bucket="value_rebound", final_score=0.95),
        _row("NEWS", bucket="news_momentum", final_score=0.70),
    ]

    def compatibility_preflight(input_rows):
        retained = [dict(row) for row in input_rows if row["symbol"] != "VALUE"]
        retained[0]["pre_backtest_strategy_compatibility"] = {
            "symbol": "NEWS",
            "status": "passed",
            "compatible_strategy_count": 2,
            "decision": "eligible_for_exact_backtest",
        }
        return retained, {
            "schema_version": "manager-research-strategy-compatibility.v1",
            "status": "completed_with_backfill",
            "rejected_symbols": ["VALUE"],
            "evaluations": [
                {
                    "symbol": "VALUE",
                    "status": "insufficient_strategy_diversity",
                    "compatible_strategy_count": 1,
                    "decision": "exclude_and_backfill",
                },
                {
                    "symbol": "NEWS",
                    "status": "passed",
                    "compatible_strategy_count": 2,
                    "decision": "eligible_for_exact_backtest",
                },
            ],
            "safety": {
                "production_authority_granted": False,
                "risk_execution_authority_granted": False,
                "backtest_thresholds_relaxed": False,
                "backtest_remains_authoritative": True,
            },
        }

    monkeypatch.setattr(
        selection_service,
        "preflight_runtime_research_strategy_compatibility",
        compatibility_preflight,
    )

    result = selection_service.select_research_backtest_candidates(
        rows,
        min_final_score=0.58,
    )

    assert [row["symbol"] for row in result["selected"]] == ["NEWS"]
    value_evaluation = next(
        row for row in result["evaluations"] if row["symbol"] == "VALUE"
    )
    assert value_evaluation["eligible"] is False
    assert "insufficient_strategy_diversity" in value_evaluation["reasons"]
    assert result["strategy_compatibility_gate"]["rejected_symbols"] == ["VALUE"]
    assert result["selected"][0]["production_entry_authorized"] is False
    assert result["selected"][0]["risk_execution_authorized"] is False

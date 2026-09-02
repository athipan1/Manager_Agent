from app.services.scanner_opportunity_service import (
    evaluate_scanner_candidate_opportunity,
    partition_scanner_candidates_by_opportunity,
)


def _candidate(
    *,
    score: float = 0.58,
    strategy_name: str = "mean_reversion",
    affinity: float = 0.80,
    hard_execution_safe: bool = True,
    thresholds_relaxed: bool = False,
    quote_status: str = "fresh",
    spread_structurally_valid: bool = True,
    liquid_spread_sane: bool = True,
):
    profile = {
        "schema_version": "scanner-opportunity-profile.v1",
        "status": "qualified",
        "workflow_status": "strategy_ready",
        "opportunity_score": score,
        "is_binding": False,
        "manager_decision_required": True,
        "fail_closed": False,
        "preferred_strategy_hint": strategy_name,
        "strategy_affinity": {
            "trend_following": 0.20,
            "breakout": 0.15,
            "mean_reversion": affinity if strategy_name == "mean_reversion" else 0.20,
            strategy_name: affinity,
        },
        "execution_context": {
            "current_price": 100.0,
            "estimated_dollar_volume": 50_000_000.0,
            "spread_bps": 8.0,
            "quote_status": quote_status,
            "market_session": "regular",
        },
        "evidence_quality": {
            "spread_structurally_valid": spread_structurally_valid,
            "liquid_spread_sane": liquid_spread_sane,
            "coverage_ratio": 1.0,
        },
        "qualification_policy": {
            "schema_version": "scanner-opportunity-qualification.v2",
            "mode": "strategy_aware",
            "strategy_bucket": "value_rebound",
            "strategy_name": strategy_name,
            "strategy_affinity": affinity,
            "generic_score": score,
            "generic_threshold": 0.70,
            "strategy_score_floor": 0.55,
            "strategy_affinity_threshold": 0.72,
            "hard_execution_safe": hard_execution_safe,
            "hard_execution_thresholds_relaxed": thresholds_relaxed,
            "manager_decision_required": True,
        },
        "reasons": ["strategy_affinity_supported"],
    }
    return {
        "symbol": "WDC",
        "confidence_score": 0.90,
        "metadata": {
            "details": {
                "data_bundle": {
                    "schema_version": "scanner-data-bundle.v1",
                    "symbol": "WDC",
                    "opportunity_profile": profile,
                }
            }
        },
    }


def test_verified_strategy_aware_candidate_below_generic_threshold_passes_manager_gate():
    result = evaluate_scanner_candidate_opportunity(
        _candidate(score=0.58),
        min_opportunity_score=0.70,
        profile_required=True,
        live_spread_required=True,
    )

    assert result["allowed"] is True
    assert result["decision"] == "PASS"
    assert result["reason_code"] == "SCANNER_OPPORTUNITY_STRATEGY_AWARE_ACCEPTED"
    assert result["strategy_aware_admission"] is True
    assert result["opportunity_score"] == 0.58
    assert result["min_opportunity_score"] == 0.70


def test_strategy_aware_claim_with_unsafe_execution_contract_is_rejected():
    result = evaluate_scanner_candidate_opportunity(
        _candidate(hard_execution_safe=False),
        min_opportunity_score=0.70,
        profile_required=True,
    )

    assert result["allowed"] is False
    assert result["reason_code"] == "SCANNER_OPPORTUNITY_STRATEGY_AWARE_INVALID"
    assert result["strategy_aware_admission"] is False


def test_strategy_aware_claim_cannot_relax_hard_execution_thresholds():
    result = evaluate_scanner_candidate_opportunity(
        _candidate(thresholds_relaxed=True),
        min_opportunity_score=0.70,
        profile_required=True,
    )

    assert result["allowed"] is False
    assert result["reason_code"] == "SCANNER_OPPORTUNITY_STRATEGY_AWARE_INVALID"


def test_stale_quote_blocks_before_strategy_aware_admission():
    result = evaluate_scanner_candidate_opportunity(
        _candidate(quote_status="stale_quote"),
        min_opportunity_score=0.70,
        profile_required=True,
    )

    assert result["allowed"] is False
    assert result["reason_code"] == "SCANNER_OPPORTUNITY_STALE_QUOTE"
    assert result["strategy_aware_admission"] is False


def test_structurally_invalid_spread_blocks_before_strategy_aware_admission():
    result = evaluate_scanner_candidate_opportunity(
        _candidate(spread_structurally_valid=False),
        min_opportunity_score=0.70,
        profile_required=True,
    )

    assert result["allowed"] is False
    assert result["reason_code"] == "SCANNER_OPPORTUNITY_FAIL_CLOSED"


def test_plain_qualified_candidate_below_generic_threshold_remains_blocked():
    candidate = _candidate(score=0.69)
    profile = candidate["metadata"]["details"]["data_bundle"]["opportunity_profile"]
    profile.pop("qualification_policy")
    profile["workflow_status"] = "ready"

    result = evaluate_scanner_candidate_opportunity(
        candidate,
        min_opportunity_score=0.70,
        profile_required=True,
    )

    assert result["allowed"] is False
    assert result["reason_code"] == "SCANNER_OPPORTUNITY_SCORE_BELOW_THRESHOLD"


def test_partition_reports_generic_and_strategy_aware_passes_separately():
    generic = _candidate(score=0.82)
    generic_profile = generic["metadata"]["details"]["data_bundle"]["opportunity_profile"]
    generic_profile["qualification_policy"]["mode"] = "generic"
    generic_profile["workflow_status"] = "ready"
    generic["symbol"] = "NVDA"
    generic["metadata"]["details"]["data_bundle"]["symbol"] = "NVDA"

    passed, review, summary = partition_scanner_candidates_by_opportunity(
        [generic, _candidate(score=0.58)],
        min_opportunity_score=0.70,
        profile_required=True,
    )

    assert len(passed) == 2
    assert review == []
    assert summary["generic_pass_count"] == 1
    assert summary["strategy_aware_pass_count"] == 1

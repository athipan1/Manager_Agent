from datetime import datetime, timezone

from app.contracts import StandardAgentResponse
from app.scanner_client import (
    SCANNER_PREFETCH_CACHE,
    _apply_scanner_candidate_gates,
    _apply_scanner_opportunity_gate,
    _cache_scanner_candidates,
)
from app.services.scanner_opportunity_service import (
    evaluate_scanner_candidate_opportunity,
    partition_scanner_candidates_by_opportunity,
    scanner_min_opportunity_score,
)


def _candidate(
    symbol="AAPL",
    *,
    quality_coverage=0.95,
    opportunity_status="qualified",
    opportunity_score=0.84,
    spread_bps=4.0,
    strategy_hint="trend_following",
    include_profile=True,
    quote_status="fresh",
    workflow_status="ready",
    fail_closed=False,
    liquid_spread_sane=True,
):
    profile = {
        "schema_version": "scanner-opportunity-profile.v1",
        "status": opportunity_status,
        "workflow_status": workflow_status,
        "opportunity_score": opportunity_score,
        "is_binding": False,
        "manager_decision_required": True,
        "fail_closed": fail_closed,
        "preferred_strategy_hint": strategy_hint,
        "strategy_affinity": {
            "trend_following": 0.88,
            "breakout": 0.72,
            "mean_reversion": 0.31,
        },
        "execution_context": {
            "current_price": 100.0,
            "average_volume": 1_000_000,
            "estimated_dollar_volume": 100_000_000.0,
            "spread_bps": spread_bps,
            "atr_pct": 0.025,
            "relative_volume": 1.5,
            "quote_timestamp": "2026-08-20T15:00:00+00:00",
            "quote_age_seconds": 1.0,
            "quote_status": quote_status,
            "market_session": "regular" if quote_status != "market_closed" else "after_hours",
            "market_open": quote_status != "market_closed",
        },
        "evidence_quality": {
            "atr_available": True,
            "relative_volume_available": True,
            "spread_available": spread_bps is not None,
            "quote_timestamp_available": True,
            "liquid_spread_sane": liquid_spread_sane,
            "spread_structurally_valid": not fail_closed,
            "coverage_ratio": 1.0,
        },
        "reasons": ["strong_trend", "strong_relative_volume"],
    }
    bundle = {
        "schema_version": "scanner-data-bundle.v1",
        "symbol": symbol,
        "data_quality": {
            "status": "complete",
            "coverage_ratio": quality_coverage,
            "missing_components": [],
            "partial_components": [],
            "market_missing_fields": [],
            "market_provider_errors": [],
        },
    }
    if include_profile:
        bundle["opportunity_profile"] = profile
    return {
        "symbol": symbol,
        "confidence_score": 0.90,
        "metadata": {
            "source": "ranked_scanner",
            "details": {"data_bundle": bundle},
        },
    }


def _response(candidates):
    return StandardAgentResponse(
        status="success",
        agent_type="scanner",
        version="1.3.0",
        timestamp=datetime.now(timezone.utc),
        correlation_id="opportunity-gate-test",
        data={
            "scan_type": "candidate_discovery",
            "count": len(candidates),
            "candidates": candidates,
            "metadata": {},
            "errors": {},
        },
    )


def test_default_min_opportunity_score_is_70_percent(monkeypatch):
    monkeypatch.delenv("SCANNER_MIN_OPPORTUNITY_SCORE", raising=False)
    assert scanner_min_opportunity_score() == 0.70


def test_qualified_profile_passes_manager_gate():
    result = evaluate_scanner_candidate_opportunity(
        _candidate(),
        min_opportunity_score=0.70,
        profile_required=True,
    )
    assert result["decision"] == "PASS"
    assert result["allowed"] is True
    assert result["opportunity_score"] == 0.84
    assert result["preferred_strategy_hint"] == "trend_following"
    assert result["compatibility_bypass"] is False
    assert result["workflow_failure"] is False


def test_review_and_avoid_profiles_fail_closed_for_production_entry():
    review = evaluate_scanner_candidate_opportunity(
        _candidate(
            opportunity_status="review",
            opportunity_score=0.65,
            workflow_status="evidence_review",
        ),
        profile_required=True,
    )
    avoid = evaluate_scanner_candidate_opportunity(
        _candidate(
            opportunity_status="avoid",
            opportunity_score=0.25,
            workflow_status="weak_opportunity",
        ),
        profile_required=True,
    )

    assert review["allowed"] is False
    assert review["reason_code"] == "SCANNER_OPPORTUNITY_REVIEW"
    assert review["research_lane_eligible"] is True
    assert avoid["allowed"] is False
    assert avoid["reason_code"] == "SCANNER_OPPORTUNITY_AVOID"
    assert avoid["research_lane_eligible"] is False


def test_market_closed_is_controlled_no_trade_not_workflow_failure():
    result = evaluate_scanner_candidate_opportunity(
        _candidate(
            opportunity_status="review",
            opportunity_score=0.72,
            quote_status="market_closed",
            workflow_status="market_closed",
        ),
        profile_required=True,
        live_spread_required=True,
    )

    assert result["allowed"] is False
    assert result["reason_code"] == "SCANNER_OPPORTUNITY_MARKET_CLOSED"
    assert result["workflow_failure"] is False
    assert result["controlled_no_trade"] is True
    assert result["research_lane_eligible"] is True


def test_stale_quote_is_controlled_review_not_workflow_failure():
    result = evaluate_scanner_candidate_opportunity(
        _candidate(
            opportunity_status="review",
            opportunity_score=0.72,
            quote_status="stale_quote",
            workflow_status="stale_quote",
        ),
        profile_required=True,
    )

    assert result["allowed"] is False
    assert result["reason_code"] == "SCANNER_OPPORTUNITY_STALE_QUOTE"
    assert result["workflow_failure"] is False
    assert result["research_lane_eligible"] is True


def test_explicit_fail_closed_profile_cannot_enter_shadow_or_production():
    result = evaluate_scanner_candidate_opportunity(
        _candidate(
            opportunity_status="avoid",
            opportunity_score=0.74,
            workflow_status="fail_closed",
            fail_closed=True,
        ),
        profile_required=True,
    )

    assert result["allowed"] is False
    assert result["reason_code"] == "SCANNER_OPPORTUNITY_FAIL_CLOSED"
    assert result["research_lane_eligible"] is False


def test_liquid_spread_sanity_failure_routes_to_review():
    result = evaluate_scanner_candidate_opportunity(
        _candidate(
            opportunity_status="review",
            opportunity_score=0.71,
            spread_bps=75.0,
            workflow_status="evidence_review",
            liquid_spread_sane=False,
        ),
        profile_required=True,
    )

    assert result["allowed"] is False
    assert result["reason_code"] == "SCANNER_OPPORTUNITY_SPREAD_SANITY"
    assert result["workflow_failure"] is False


def test_present_profile_below_manager_threshold_is_blocked_even_if_scanner_says_qualified():
    result = evaluate_scanner_candidate_opportunity(
        _candidate(opportunity_status="qualified", opportunity_score=0.69),
        min_opportunity_score=0.70,
        profile_required=False,
    )
    assert result["allowed"] is False
    assert result["reason_code"] == "SCANNER_OPPORTUNITY_SCORE_BELOW_THRESHOLD"


def test_missing_profile_has_explicit_transition_semantics():
    optional = evaluate_scanner_candidate_opportunity(
        _candidate(include_profile=False),
        profile_required=False,
    )
    required = evaluate_scanner_candidate_opportunity(
        _candidate(include_profile=False),
        profile_required=True,
    )

    assert optional["allowed"] is True
    assert optional["compatibility_bypass"] is True
    assert optional["reason_code"] == "SCANNER_OPPORTUNITY_PROFILE_OPTIONAL_MISSING"
    assert required["allowed"] is False
    assert required["reason_code"] == "SCANNER_OPPORTUNITY_PROFILE_MISSING"


def test_live_spread_can_be_required_for_automated_entry():
    result = evaluate_scanner_candidate_opportunity(
        _candidate(spread_bps=None),
        profile_required=True,
        live_spread_required=True,
    )
    assert result["allowed"] is False
    assert result["reason_code"] == "SCANNER_OPPORTUNITY_LIVE_SPREAD_MISSING"


def test_scanner_cannot_claim_binding_authority():
    candidate = _candidate()
    profile = candidate["metadata"]["details"]["data_bundle"]["opportunity_profile"]
    profile["is_binding"] = True

    result = evaluate_scanner_candidate_opportunity(candidate, profile_required=True)
    assert result["allowed"] is False
    assert result["reason_code"] == "SCANNER_OPPORTUNITY_AUTHORITY_INVALID"


def test_unknown_strategy_hint_is_rejected():
    result = evaluate_scanner_candidate_opportunity(
        _candidate(strategy_hint="magic_alpha"),
        profile_required=True,
    )
    assert result["allowed"] is False
    assert result["reason_code"] == "SCANNER_OPPORTUNITY_STRATEGY_HINT_INVALID"


def test_partition_exposes_compatibility_and_controlled_no_trade_counts():
    passed, review, summary = partition_scanner_candidates_by_opportunity(
        [
            _candidate("AAPL"),
            _candidate("MSFT", include_profile=False),
            _candidate(
                "NVDA",
                opportunity_status="review",
                quote_status="market_closed",
                workflow_status="market_closed",
            ),
        ],
        profile_required=False,
    )
    assert len(passed) == 2
    assert len(review) == 1
    assert summary["compatibility_bypass_count"] == 1
    assert summary["controlled_no_trade_count"] == 1
    assert summary["workflow_failure_count"] == 0
    assert summary["research_lane_eligible_count"] == 1


def test_combined_gates_move_low_opportunity_candidate_to_review_before_cache(monkeypatch):
    monkeypatch.setenv("SCANNER_MIN_DATA_COVERAGE", "0.80")
    monkeypatch.setenv("SCANNER_OPPORTUNITY_PROFILE_REQUIRED", "true")
    monkeypatch.setenv("SCANNER_MIN_OPPORTUNITY_SCORE", "0.70")
    SCANNER_PREFETCH_CACHE.clear()

    gated = _apply_scanner_candidate_gates(
        _response(
            [
                _candidate("AAPL", opportunity_score=0.84),
                _candidate(
                    "TSLA",
                    opportunity_status="review",
                    opportunity_score=0.62,
                    workflow_status="evidence_review",
                ),
            ]
        )
    )
    data = gated.data.model_dump(mode="json")

    assert [row["symbol"] for row in data["candidates"]] == ["AAPL"]
    assert data["count"] == 1
    assert data["review_candidates"][0]["symbol"] == "TSLA"
    opportunity_summary = data["metadata"]["scanner_opportunity_gate"]
    assert opportunity_summary["passed_count"] == 1
    assert opportunity_summary["review_count"] == 1

    _cache_scanner_candidates(gated)
    assert "AAPL" in SCANNER_PREFETCH_CACHE
    assert "TSLA" not in SCANNER_PREFETCH_CACHE


def test_opportunity_gate_preserves_prior_data_quality_review_diagnostics(monkeypatch):
    monkeypatch.setenv("SCANNER_OPPORTUNITY_PROFILE_REQUIRED", "true")
    response = _response(
        [
            _candidate("AAPL"),
        ]
    )
    payload = response.model_dump(mode="json")
    payload["data"]["review_candidates"] = [
        {
            "symbol": "AMD",
            "decision": "REVIEW",
            "reason_code": "SCANNER_DATA_COVERAGE_BELOW_THRESHOLD",
        }
    ]
    gated = _apply_scanner_opportunity_gate(StandardAgentResponse.model_validate(payload))
    data = gated.data.model_dump(mode="json")

    assert data["review_candidates"][0]["symbol"] == "AMD"
    assert data["candidates"][0]["symbol"] == "AAPL"
